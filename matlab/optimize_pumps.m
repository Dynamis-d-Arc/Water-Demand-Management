% optimize_pumps.m  Prototype day-ahead pump schedule (QW2) checked with EPANET (QW3).
% Run from water_poc:   matlab -batch "run('matlab/optimize_pumps.m')"
%
% Customers are fed by gravity from the two head tanks (NPL2_HT, NPL3_HT), so tank level is
% what holds their pressure. Each day starts at the model's tank levels, capped at 85% of the
% tank range so there is room to fill, and plans keep tanks below 90% so they stay clear of
% EPANET's full-tank shut-off. For each demand scenario:
% 1. Every combination of pumps running at the three stations (NPL2 0-6, NPL3 0-6,
%    TM Pond 0-6 = 343 combinations) is solved in EPANET as a snapshot, giving its pump power,
%    the pressure at each customer node and the net flow into each tank. Tank flows are
%    measured at the start level and at the plan ceiling, and their average is used.
% 2. intlinprog picks the pumps running in each hour, keeping each tank between its reserve
%    and 97% and ending the day at least as full as it started (so the plan can repeat).
%    When the snapshots show that power and tank flows add up station by station (checked
%    against every snapshot), it chooses a pump count per station per hour; otherwise one
%    combination per hour.
% 3. Every schedule is run through validate_plan (24 h EPANET simulation). If a tank falls
%    below its reserve or ends low, or a customer falls below its floor, the tank reserve or
%    end level is raised and the schedule re-optimised (up to 6 rounds).
%
% Schedules:
%   Reference       lowest energy, ignores the tariff (what good operation achieves without
%                   time-of-use scheduling); tank reserve 10%, pressure margin 0 m
%   A lowest cost   lowest cost under the tariff; reserve 10%, margin 0 m
%   C balanced      lowest cost; reserve 30%, margin 1 m
%   B lower risk    lowest cost; reserve 50%, margin 2 m
% Plans are compared with the reference, so the saving shown is what the tariff-aware
% schedule adds; a plan that never passes the EPANET check shows no saving. A plan passes when
% EPANET keeps each tank above the plan's reserve; the MILP may plan with a higher reserve to
% get there. Customer floor = 10 m, or the model's own minimum where it is below 10 m.
%
% Scenarios: the model's demand (688k m3/day) and the same without nodes 71 and 678, which
% carry 100k m3/day each and look like placeholders.
% ASSUMPTIONS to replace with Eastwater data: weekday TOU tariff below, all pumps available,
% flat demand (the model has no demand pattern), 75% pump efficiency (model setting).
% Writes reports/matlab/pump_plans.md, pump_plans_kpis.csv, pump_plans_scenarios.csv,
% pump_plans_schedule.csv and pump_plans_<scenario>.png.

root = fileparts(fileparts(mfilename('fullpath')));
addpath(fileparts(mfilename('fullpath')));
outDir = fullfile(root, 'reports', 'matlab');
if ~isfolder(outDir), mkdir(outDir); end
inp = fullfile(fileparts(root), 'Demand-2023 v20RY to MTP new TM2P.inp');

% Illustrative weekday TOU tariff, THB/kWh (peak 09:00-22:00). ASSUMPTION: replace with actual.
cfg.peak = 4.1839;
cfg.offPeak = 2.6037;
cfg.tariff = cfg.offPeak * ones(24, 1);
cfg.tariff(10:22) = cfg.peak;
cfg.hours = 24;
cfg.maxRounds = 6;
cfg.startCap = 0.85;
cfg.planMax = 0.90;
cfg.stations = ["NPL2-", "NPL3-", "TM_Pond_"];
cfg.plans = struct('name', {"Reference (lowest energy, ignores tariff)", "Plan A lowest cost", ...
                            "Plan C balanced", "Plan B lower risk"}, ...
                   'reserve', {0.10, 0.10, 0.30, 0.50}, 'margin', {0, 0, 1, 2}, ...
                   'tariffAware', {false, true, true, true});
scenarios = struct('key', {"model_demand", "no_placeholders"}, ...
                   'name', {"Model demand", "Without placeholder nodes 71 and 678"}, ...
                   'zeroNodes', {strings(0, 1), ["71"; "678"]});

% The model as supplied, for reference and for the customer pressure floors
[d, c] = load_network(inp);
pumps = d.getLinkPumpIndex;
pumpNames = string(d.getLinkNameID(pumps));
cfg.station = zeros(numel(pumps), 1);
for s = 1:numel(cfg.stations)
    cfg.station(startsWith(pumpNames, cfg.stations(s))) = s;
end
ref = validate_plan(d, struct('hours', cfg.hours, 'tariff', cfg.tariff), struct('targetPressure', 10));
refOn = repmat(double(d.getLinkInitialStatus(pumps)), cfg.hours, 1);
clear c
cfg.floor = dictionary(ref.customers.node, min(10, ref.customers.min_pressure_m));

L = strings(0, 1);
L(end+1) = "# Pump schedule prototype (QW2) checked with EPANET (QW3)";
L(end+1) = "";
L(end+1) = sprintf("Network `%s`, one weekday, flat demand. Head tanks start at the model's levels capped at %.0f%% " + ...
    "of their range; plans keep them below %.0f%%. 343 station combinations solved in EPANET; schedules chosen by " + ...
    "`intlinprog` and checked in a 24 h EPANET run (`validate_plan`).", 'Demand-2023 v20RY to MTP new TM2P.inp', ...
    100 * cfg.startCap, 100 * cfg.planMax);
L(end+1) = "";
L(end+1) = sprintf("**Assumed tariff** (replace with Eastwater's): %.4f THB/kWh peak 09:00-22:00, %.4f off-peak. " + ...
    "All pumps assumed available; model pump efficiency 75%%. Customer floor = 10 m, or the model's own minimum " + ...
    "where it is already lower (Burapa, IEAT4/5/6).", cfg.peak, cfg.offPeak);
L(end+1) = "";
L(end+1) = sprintf("Model as supplied (14 pumps all day, from its own start levels): %s, %s kWh/day, %.4f kWh/m3, " + ...
    "%.4f THB/m3. %s.", ref.status, fmtNum(ref.kpi.energy_kwh), ref.kpi.kwh_per_m3, ref.kpi.thb_per_m3, ...
    strjoin([ref.reasons(:); ref.notes(:)], "; "));
L(end+1) = "";

sched = table();
kpis = kpiTable(kpiCells("Model as supplied", "Model operation (14 pumps all day)", ref, true, ref, ...
                         "itself", refOn, []));
info = table();
for sc = scenarios
    [lines, t, kp, si] = runScenario(inp, sc, cfg, outDir);
    L = [L(:); lines(:)];
    sched = [sched; t]; %#ok<AGROW>
    kpis = [kpis; kp]; %#ok<AGROW>
    info = [info; si]; %#ok<AGROW>
    fprintf('%s done\n', sc.name);
end
writetable(kpis, fullfile(outDir, 'pump_plans_kpis.csv'));
writetable(info, fullfile(outDir, 'pump_plans_scenarios.csv'));
L(end+1) = "Hourly schedules: reports/matlab/pump_plans_schedule.csv.";
writetable(sched, fullfile(outDir, 'pump_plans_schedule.csv'));
writelines(L, fullfile(outDir, 'pump_plans.md'));
fprintf('%s\n', L);

%% ------------------------------------------------------------------ scenario

function [L, sched, kp, info] = runScenario(inp, sc, cfg, outDir)
hours = cfg.hours;
tariff = cfg.tariff;
station = cfg.station;

% 1. Snapshot every station combination at the start levels
[d, c] = loadScenario(inp, sc, cfg.startCap);
pumps = d.getLinkPumpIndex;
tanks = d.getNodeTankIndex;
tankNames = string(d.getNodeNameID(tanks));
area = pi * d.getNodeTankDiameter.^2 / 4;
lvlMin = d.getNodeTankMinimumWaterLevel;
lvlMax = d.getNodeTankMaximumWaterLevel;
lvl0 = d.getNodeTankInitialLevel;
junc = d.getNodeJunctionIndex;
bd = d.getNodeBaseDemands;
cust = junc(bd{1}(junc) > 0);
custNames = string(d.getNodeNameID(cust));
floorP = reshape(cfg.floor(custNames(:)), 1, []);      % row, customer order
demand = sum(bd{1}(cust));
d.setTimeSimulationDuration(0);
[n2, n3, nt] = ndgrid(0:6, 0:6, 0:6);
combos = [n2(:), n3(:), nt(:)];
nc = size(combos, 1);
P = nan(nc, 1);
Q = nan(nc, numel(tanks));
custP = nan(nc, numel(cust));
code = nan(nc, 1);
for k = 1:nc
    d.setLinkInitialStatus(pumps, pumpsFor(combos(k, :), station)');
    d.openHydraulicAnalysis;
    d.initializeHydraulicAnalysis(0);
    d.runHydraulicAnalysis;
    code(k) = d.Errcode;
    p = d.getNodePressure;
    dem = d.getNodeActualDemand;
    P(k) = sum(d.getLinkEnergy(pumps));
    Q(k, :) = dem(tanks) / 24;                         % net inflow to each tank, m3/h
    custP(k, :) = p(cust);
    d.closeHydraulicAnalysis;
end
% Pumps deliver less into a fuller tank, so measure the tank flows again at the plan ceiling
% and plan on the average of the two levels. (Planning on the lower one overfills the tanks:
% EPANET then shuts the pumps off against the full tank and the tank drains.)
Qstart = Q;
d.setNodeTankInitialLevel(lvlMin + cfg.planMax * (lvlMax - lvlMin));
for k = 1:nc
    d.setLinkInitialStatus(pumps, pumpsFor(combos(k, :), station)');
    d.openHydraulicAnalysis;
    d.initializeHydraulicAnalysis(0);
    d.runHydraulicAnalysis;
    dem = d.getNodeActualDemand;
    Q(k, :) = (Q(k, :) + dem(tanks) / 24) / 2;
    d.closeHydraulicAnalysis;
end
clear c
ok = ~(code == 1 | code == 3 | code == 4 | code > 100);
model = additiveFit(combos(ok, :), P(ok), Q(ok, :));
V0 = area .* lvl0;
Vmax = area .* (lvlMin + cfg.planMax * (lvlMax - lvlMin));
feas0 = ok & all(custP >= floorP, 2);
[~, maxPump] = max(min(Qstart, [], 2) + 1e-3 * sum(Qstart, 2) - 1e9 * ~feas0);   % drains the tanks least

% 2-3. Optimise and check each schedule
plans = cfg.plans;
for ip = 1:numel(plans)
    objTariff = tariff;
    if ~plans(ip).tariffAware, objTariff(:) = mean(tariff); end      % minimise energy only
    spec = plans(ip).reserve * ones(1, numel(tanks));   % what EPANET must show
    reserve = spec;                                      % what the MILP plans with; raised if needed
    margin = plans(ip).margin;
    endExtra = zeros(1, numel(tanks));
    best = [];
    converged = false;
    for iter = 1:cfg.maxRounds
        feas = ok & all(custP >= floorP + margin, 2);
        Vmin = area .* (lvlMin + reserve .* (lvlMax - lvlMin));
        t0 = tic;
        [counts, exitflag, gap, method] = planSchedule(combos, feas, P, Q, model, objTariff, Vmin, Vmax, V0, ...
                                                       min(V0 + endExtra, Vmax));
        fprintf('  %s / %s round %d: %s MILP, %d valid combinations, %.1f s, exitflag %d\n', ...
                sc.name, plans(ip).name, iter, method, nnz(feas), toc(t0), exitflag);
        if exitflag <= 0, break; end
        on = zeros(hours, numel(pumps));
        for h = 1:hours
            on(h, :) = pumpsFor(counts(h, :), station);
        end
        [d, c] = loadScenario(inp, sc, cfg.startCap);
        R = validate_plan(d, struct('hours', hours, 'pumpOn', on, 'tariff', tariff), ...
                          struct('targetPressure', floorP(:) + margin, 'endTankTol', 0.25));
        clear c
        best = struct('R', R, 'on', on, 'gap', gap, 'method', method, 'reserve', spec, 'planned', reserve);
        lowTank = R.tanks.min_m' < lvlMin + spec .* (lvlMax - lvlMin) - 0.05;
        lowP = R.customers.min_pressure_m < floorP(:) + margin - 0.05;
        lowEnd = R.tanks.end_m' < R.tanks.start_m' - 0.25;
        if R.status ~= "Fail" && ~any(lowTank) && ~any(lowP) && ~any(lowEnd)
            converged = true;
            break
        end
        % A low end level or low pressure also raises the reserve: shallower drawdowns keep the
        % linear tank model closer to EPANET, and pressure comes from tank head.
        cap = cfg.planMax - 0.15;                        % keep a band between reserve and ceiling
        reserve(lowTank) = min(reserve(lowTank) + 0.05, cap);
        if any(lowP) || any(lowEnd), reserve = min(reserve + 0.05, cap); end
        endExtra(lowEnd) = endExtra(lowEnd) + 0.02 * area(lowEnd) .* (lvlMax(lowEnd) - lvlMin(lowEnd));
    end
    plans(ip).best = best;
    plans(ip).converged = converged;
    plans(ip).rounds = iter;
end

% Comparator: the reference schedule, or the model's own operation if no schedule exists
if ~isempty(plans(1).best)
    cmp = plans(1).best.R;
    cmpName = "the reference";
    extra = struct('name', {}, 'R', {}, 'on', {});
else
    onMax = repmat(pumpsFor(combos(maxPump, :), station)', hours, 1);
    [d, c] = loadScenario(inp, sc, cfg.startCap);
    Rmax = validate_plan(d, struct('hours', hours, 'pumpOn', onMax, 'tariff', tariff), ...
                         struct('targetPressure', floorP(:), 'endTankTol', 0.25));
    clear c
    cmp = Rmax;
    cmpName = sprintf("the model's operation (%d + %d + %d pumps all day)", combos(maxPump, :));
    extra = struct('name', "Model operation (" + strjoin(string(combos(maxPump, :)), " + ") + " pumps all day)", ...
                   'R', Rmax, 'on', onMax);
end

% Figure
shown = [extra, struct('name', {}, 'R', {}, 'on', {})];
for ip = 1:numel(plans)
    if ~isempty(plans(ip).best)
        shown(end+1) = struct('name', plans(ip).name, 'R', plans(ip).best.R, 'on', plans(ip).best.on); %#ok<AGROW>
    end
end
sched = table();
if ~isempty(shown)
    fig = figure('Visible', 'off', 'Position', [100 100 1150 230 * numel(shown)]);
    theme(fig, 'light');
    tl = tiledlayout(fig, numel(shown), 2, 'TileSpacing', 'compact');
    for i = 1:numel(shown)
        plotPlan(tl, shown(i).name, shown(i).on, shown(i).R, station, lvlMin, lvlMax, tankNames, i == 1);
        sched = [sched; scheduleTable(sc.name, shown(i).name, shown(i).on, station, tariff)]; %#ok<AGROW>
    end
    xlabel(tl, 'hour of day (shaded = peak tariff)');
    title(tl, sc.name, 'FontWeight', 'bold');
    exportgraphics(fig, fullfile(outDir, "pump_plans_" + sc.key + ".png"), 'Resolution', 100);
end

% Report section
L = strings(0, 1);
L(end+1) = sprintf("## %s: %s m3/day", sc.name, fmtNum(demand));
L(end+1) = "";
L(end+1) = sprintf("Start levels %s m (%s of range). %d of %d station combinations are hydraulically valid; at most " + ...
    "%d TM Pond pumps can run (more gives EPANET 'pumps cannot deliver head'). Station-additive fit of the snapshots: " + ...
    "power within %.1f kW, tank flows within %.1f m3/h (%s).", strjoin(compose("%.2f", lvl0), " / "), ...
    strjoin(compose("%.0f%%", 100 * (lvl0 - lvlMin) ./ (lvlMax - lvlMin)), " / "), nnz(ok), nc, ...
    max(combos(ok, 3)), model.maxErrP, model.maxErrQ, string(ifelse(model.good, "used by the MILP", "not used")));
L(end+1) = sprintf("Most pumping that still meets the pressure floors (%d + %d + %d pumps) gives net tank flows of %s m3/h " + ...
    "(%s m3/day).", combos(maxPump, :), strjoin(compose("%+.0f", Qstart(maxPump, :)), " / "), ...
    strjoin(compose("%+.0f", 24 * Qstart(maxPump, :)), " / "));
L(end+1) = "";
L(end+1) = "| schedule | EPANET check | energy kWh/day | cost THB/day | kWh/m3 | THB/m3 | cost vs " + cmpName + ...
    " | lowest customer pressure m | tank reserve | pump starts | pumps on at peak (avg) |";
L(end+1) = "|---|---|---|---|---|---|---|---|---|---|---|";
for i = 1:numel(extra)
    L(end+1) = kpiRow(extra(i).name, extra(i).R, "", cmp, extra(i).on, []); %#ok<AGROW>
end
for ip = 1:numel(plans)
    b = plans(ip).best;
    if isempty(b)
        L(end+1) = sprintf("| %s | no feasible schedule | | | | | | | | | |", plans(ip).name); %#ok<AGROW>
    else
        tag = "";
        if ~plans(ip).converged, tag = " (not converged)"; end
        L(end+1) = kpiRow(plans(ip).name, b.R, tag, cmp, b.on, b.reserve); %#ok<AGROW>
    end
end
L(end+1) = "";
for i = 1:numel(extra)
    L(end+1) = extra(i).name + " - " + checkText(extra(i).R) + "."; %#ok<AGROW>
end
for ip = 1:numel(plans)
    b = plans(ip).best;
    if isempty(b)
        L(end+1) = plans(ip).name + " - no schedule keeps the tanks within limits and ends the day as full as it started."; %#ok<AGROW>
    else
        L(end+1) = sprintf("%s (%d round(s), %s MILP, gap %s) - %s.", plans(ip).name, plans(ip).rounds, b.method, ...
            gapText(b.gap), checkText(b.R)); %#ok<AGROW>
    end
end
L(end+1) = "Tank reserve is per tank (" + strjoin(tankNames, " / ") + "). Figure: reports/matlab/pump_plans_" + sc.key + ".png.";
L(end+1) = "";

% The same results as tables, for the dashboard
rows = cell(0, numel(kpiNames()));
for i = 1:numel(extra)
    rows(end+1, :) = kpiCells(sc.name, extra(i).name, extra(i).R, true, cmp, cmpName, extra(i).on, []); %#ok<AGROW>
end
for ip = 1:numel(plans)
    b = plans(ip).best;
    if isempty(b)
        rows(end+1, :) = {sc.name, plans(ip).name, false, "no feasible schedule", false, NaN, NaN, NaN, NaN, ...
                          NaN, cmpName, NaN, "", NaN, NaN}; %#ok<AGROW>
    else
        rows(end+1, :) = kpiCells(sc.name, plans(ip).name, b.R, plans(ip).converged, cmp, cmpName, b.on, b.reserve); %#ok<AGROW>
    end
end
kp = kpiTable(rows);
info = table(sc.name, sc.key, demand, nnz(ok), nc, max(combos(ok, 3)), ...
    sprintf("%d + %d + %d", combos(maxPump, :)), tankNames(1), 24 * Qstart(maxPump, 1), tankNames(2), 24 * Qstart(maxPump, 2), ...
    'VariableNames', {'scenario', 'key', 'demand_m3_day', 'valid_combinations', 'combinations', 'max_tm_pond_pumps', ...
    'max_pumping_npl2_npl3_tm', 'tank1', 'tank1_net_flow_m3_day', 'tank2', 'tank2_net_flow_m3_day'});
end

function n = kpiNames()
n = {'scenario', 'schedule', 'feasible', 'status', 'converged', 'energy_kwh', 'cost_thb', 'kwh_per_m3', ...
     'thb_per_m3', 'cost_vs_comparator_pct', 'comparator', 'min_customer_pressure_m', 'tank_reserve', ...
     'pump_starts', 'peak_pumps_avg'};
end

function t = kpiTable(rows)
t = cell2table(rows, 'VariableNames', kpiNames());
for v = ["scenario", "schedule", "status", "comparator", "tank_reserve"]
    t.(v) = string(t.(v));
end
end

function c = kpiCells(scenario, name, R, converged, cmp, cmpName, on, reserve)
% One KPI row; a schedule that never passed the EPANET check gets no saving figure
starts = sum(sum(max(diff(on, 1, 1), 0)));
if isempty(reserve), res = ""; else, res = strjoin(compose("%.0f%%", 100 * reserve), " / "); end
vs = NaN;
if converged, vs = 100 * (R.kpi.cost_thb / cmp.kpi.cost_thb - 1); end
c = {scenario, name, true, R.status, converged, R.kpi.energy_kwh, R.kpi.cost_thb, R.kpi.kwh_per_m3, ...
     R.kpi.thb_per_m3, vs, cmpName, R.kpi.min_customer_pressure_m, res, starts, mean(sum(on(10:22, :), 2))};
end

%% ------------------------------------------------------------------ optimisation

function M = additiveFit(C, P, Q)
% Does power / tank flow = sum of one term per station (count 0..6)? Fitted on valid snapshots.
X = zeros(size(C, 1), 21);
for s = 1:3
    X(sub2ind(size(X), (1:size(C, 1))', (s - 1) * 7 + C(:, s) + 1)) = 1;
end
M.p = lsqminnorm(X, P);
M.q = lsqminnorm(X, Q);
M.maxErrP = max(abs(X * M.p - P));
M.maxErrQ = max(abs(X * M.q - Q), [], 'all');
M.good = M.maxErrP <= max(5, 0.002 * max(P)) && M.maxErrQ <= 20;
end

function [counts, exitflag, gap, method] = planSchedule(combos, feas, P, Q, model, tariff, Vmin, Vmax, V0, Vend)
counts = [];
gap = NaN;
F = combos(feas, :);
if isempty(F)
    exitflag = -2;
    method = "no";
    return
end
allowed = arrayfun(@(s) unique(F(:, s))', 1:3, 'UniformOutput', false);
isProduct = size(F, 1) == prod(cellfun(@numel, allowed));
if isProduct && model.good
    method = "station";
    [counts, exitflag, gap] = solveStations(allowed, model, tariff, Vmin, Vmax, V0, Vend);
else
    method = "combination";
    [pick, exitflag, gap] = solveCombos(P(feas), Q(feas, :), tariff, Vmin, Vmax, V0, Vend);
    if exitflag > 0, counts = F(pick, :); end
end
end

function [counts, exitflag, gap] = solveStations(allowed, model, tariff, Vmin, Vmax, V0, Vend)
% Binary y(h, s, j): station s runs j pumps in hour h. One j per station-hour.
H = numel(tariff);
nT = size(model.q, 2);
vars = zeros(0, 3);
for h = 1:H
    for s = 1:3
        for j = allowed{s}
            vars(end+1, :) = [h, s, j]; %#ok<AGROW>
        end
    end
end
col = (vars(:, 2) - 1) * 7 + vars(:, 3) + 1;
nx = size(vars, 1);
nv = nT * (H + 1);
vi = @(k, h) nx + (k - 1) * (H + 1) + h + 1;
f = [tariff(vars(:, 1)) .* model.p(col); zeros(nv, 1)];
Aeq = sparse(3 * H + nT * H, nx + nv);
beq = zeros(3 * H + nT * H, 1);
r = 0;
for h = 1:H
    for s = 1:3
        r = r + 1;
        Aeq(r, vars(:, 1) == h & vars(:, 2) == s) = 1;
        beq(r) = 1;
    end
end
for k = 1:nT
    for h = 1:H
        r = r + 1;
        inHour = find(vars(:, 1) == h);
        Aeq(r, vi(k, h)) = 1;
        Aeq(r, vi(k, h - 1)) = -1;
        Aeq(r, inHour) = -model.q(col(inHour), k)';
    end
end
[lb, ub] = volumeBounds(nx, nT, H, vi, Vmin, Vmax, V0, Vend);
[z, exitflag, gap] = runMilp(f, nx, Aeq, beq, lb, ub);
counts = zeros(H, 3);
if exitflag > 0
    for i = find(round(z(1:nx)) == 1)'
        counts(vars(i, 1), vars(i, 2)) = vars(i, 3);
    end
end
end

function [pick, exitflag, gap] = solveCombos(P, Q, tariff, Vmin, Vmax, V0, Vend)
% Binary x(h, c): combination c runs in hour h. One combination per hour.
H = numel(tariff);
m = numel(P);
nT = size(Q, 2);
nx = H * m;
nv = nT * (H + 1);
xi = @(h) (h - 1) * m + (1:m);
vi = @(k, h) nx + (k - 1) * (H + 1) + h + 1;
f = [kron(tariff, P); zeros(nv, 1)];
Aeq = sparse(H + nT * H, nx + nv);
beq = zeros(H + nT * H, 1);
r = 0;
for h = 1:H
    r = r + 1;
    Aeq(r, xi(h)) = 1;
    beq(r) = 1;
end
for k = 1:nT
    for h = 1:H
        r = r + 1;
        Aeq(r, vi(k, h)) = 1;
        Aeq(r, vi(k, h - 1)) = -1;
        Aeq(r, xi(h)) = -Q(:, k)';
    end
end
[lb, ub] = volumeBounds(nx, nT, H, vi, Vmin, Vmax, V0, Vend);
[z, exitflag, gap] = runMilp(f, nx, Aeq, beq, lb, ub);
pick = zeros(H, 1);
if exitflag > 0
    [~, pick] = max(reshape(round(z(1:nx)), m, H), [], 1);
    pick = pick(:);
end
end

function [lb, ub] = volumeBounds(nx, nT, H, vi, Vmin, Vmax, V0, Vend)
% Tank volumes start at V0, stay within [Vmin, Vmax] and end at or above Vend
lb = zeros(nx + nT * (H + 1), 1);
ub = [ones(nx, 1); inf(nT * (H + 1), 1)];
for k = 1:nT
    lb(vi(k, 0)) = V0(k);
    ub(vi(k, 0)) = V0(k);
    for h = 1:H
        lb(vi(k, h)) = Vmin(k);
        ub(vi(k, h)) = Vmax(k);
    end
    lb(vi(k, H)) = max(Vmin(k), Vend(k));
end
end

function [z, exitflag, gap] = runMilp(f, nx, Aeq, beq, lb, ub)
% Many schedules cost almost the same, so stop at a 0.5% optimality gap. Stopping on the gap
% (not the clock) keeps runs reproducible; the time limit is only a safety net.
opts = optimoptions('intlinprog', 'Display', 'off', 'MaxTime', 300, 'RelativeGapTolerance', 5e-3);
[z, ~, exitflag, out] = intlinprog(f, 1:nx, [], [], Aeq, beq, lb, ub, opts);
gap = out.relativegap;
end

%% ------------------------------------------------------------------ helpers

function [d, c] = loadScenario(inp, sc, startCap)
[d, c] = load_network(inp);
for n = sc.zeroNodes(:)'
    d.setNodeBaseDemands(d.getNodeIndex(char(n)), 0);
end
lmin = d.getNodeTankMinimumWaterLevel;
lmax = d.getNodeTankMaximumWaterLevel;
d.setNodeTankInitialLevel(min(d.getNodeTankInitialLevel, lmin + startCap * (lmax - lmin)));
end

function on = pumpsFor(n, station)
% First n(s) pumps of each station switched on (pumps in a station share one curve)
on = zeros(numel(station), 1);
for s = 1:numel(n)
    members = find(station == s);
    on(members(1:n(s))) = 1;
end
end

function plotPlan(tl, name, on, R, station, lvlMin, lvlMax, tankNames, withLegend)
hours = size(on, 1);
counts = zeros(hours, max(station));
for s = 1:max(station), counts(:, s) = sum(on(:, station == s), 2); end
ax = nexttile(tl);
xregion(ax, 9, 22, 'FaceColor', [0.93 0.93 0.93]);
hold(ax, 'on');
hs = stairs(ax, 0:hours, [counts; counts(end, :)], 'LineWidth', 1.4);
title(ax, name + ": pumps running", 'FontWeight', 'normal');
ylabel(ax, 'pumps'); ylim(ax, [-0.2 6.4]); xlim(ax, [0 hours]); grid(ax, 'on');
if withLegend, legend(ax, hs, ["NPL2", "NPL3", "TM Pond"], 'Location', 'eastoutside'); end
ax = nexttile(tl);
xregion(ax, 9, 22, 'FaceColor', [0.93 0.93 0.93]);
hold(ax, 'on');
hp = plot(ax, R.steps.time_h, 100 * (R.tankLevels - lvlMin) ./ (lvlMax - lvlMin), 'LineWidth', 1.4);
title(ax, name + ": tank level (EPANET)", 'FontWeight', 'normal');
ylabel(ax, '% of range'); ylim(ax, [0 100]); xlim(ax, [0 hours]); grid(ax, 'on');
if withLegend, legend(ax, hp, tankNames, 'Location', 'eastoutside', 'Interpreter', 'none'); end
end

function t = scheduleTable(scenario, plan, on, station, tariff)
hours = size(on, 1);
counts = zeros(hours, max(station));
for s = 1:max(station), counts(:, s) = sum(on(:, station == s), 2); end
t = table(repmat(scenario, hours, 1), repmat(plan, hours, 1), (0:hours-1)', counts(:, 1), counts(:, 2), ...
          counts(:, 3), tariff, 'VariableNames', {'scenario', 'schedule', 'hour', 'npl2_pumps', 'npl3_pumps', ...
          'tm_pond_pumps', 'tariff_thb_per_kwh'});
end

function row = kpiRow(name, R, tag, cmp, on, reserve)
starts = sum(sum(max(diff(on, 1, 1), 0)));
if isempty(reserve), res = "-"; else, res = strjoin(compose("%.0f%%", 100 * reserve), " / "); end
if tag == "", vs = sprintf("%+.1f%%", 100 * (R.kpi.cost_thb / cmp.kpi.cost_thb - 1)); else, vs = "n/a (not valid)"; end
row = sprintf("| %s | %s%s | %s | %s | %.4f | %.4f | %s | %.2f | %s | %d | %.1f |", name, R.status, tag, ...
    fmtNum(R.kpi.energy_kwh), fmtNum(R.kpi.cost_thb), R.kpi.kwh_per_m3, R.kpi.thb_per_m3, vs, ...
    R.kpi.min_customer_pressure_m, res, starts, mean(sum(on(10:22, :), 2)));
end

function txt = checkText(R)
items = [R.reasons(:); R.notes(:)];
if isempty(items), txt = "all checks passed"; else, txt = strjoin(items, "; "); end
end

function txt = gapText(gap)
if isempty(gap) || ~isfinite(gap), txt = "n/a"; else, txt = sprintf("%.2f%%", 100 * gap); end
end

function v = ifelse(cond, a, b)
if cond, v = a; else, v = b; end
end

function s = fmtNum(x)
s = string(regexprep(sprintf('%.0f', x), '(\d)(?=(\d{3})+$)', '$1,'));
end
