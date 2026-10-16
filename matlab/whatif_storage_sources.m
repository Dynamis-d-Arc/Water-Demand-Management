% whatif_storage_sources.m  Where could pumping savings come from? Two what-ifs on the Rayong model.
% Run from water_poc:   matlab -batch "run('matlab/whatif_storage_sources.m')"
%
% (a) Storage: how much head-tank storage would make time-of-use (TOU) pumping pay?
%     NPL2_HT and NPL3_HT are scaled to 1x, 2x, 5x and 10x their volume (diameter x sqrt(k); levels
%     unchanged, so each level gives customers the same pressure as today). For each size the
%     lowest-energy reference and the lowest-cost (tariff-aware) schedule are chosen by a
%     station-level MILP (intlinprog, 0.5% gap, 300 s limit) and checked in a 24 h EPANET run
%     (validate_plan), as in optimize_pumps.m: up to 6 optimise-and-check rounds, each plan judged
%     against a fixed spec (tank reserve 10%, customer floors, end at least as full as the start)
%     while only the planning margins are raised. A saving counts only when both plans pass.
%     Two changes from optimize_pumps.m, because bigger tanks swing over a wide band of levels:
%     - Tank level matters. Between half full and 90% full the tank inflows, pump power and
%       customer pressures change a lot, and NPL2 pumps run off the end of their curve at low
%       levels. So every station combination is solved on a grid of tank levels, and inflows, power
%       and pressures are fitted linear in the two tank levels for each station pump count (still
%       additive station by station). The MILP multiplies the pump choice by the start-of-hour level
%       exactly, so it steps the tanks hour by hour with start-of-hour flows, as EPANET does with
%       1 h steps. Customer floors and the pump-curve limit are constraints in every hour.
%     - The day's start level is chosen by the optimiser and the day must end at least as full (a
%       repeatable day). Starting at 85% at midnight, as optimize_pumps.m does, leaves only
%       22:00-24:00 to refill after the peak, which caps what any tank size can shift. One extra plan
%       at the largest size keeps that start rule, to show what it costs.
%     Solver: binaries are "at least k pumps" per station-hour (same bound as one binary per count,
%     several times faster); lowest-cost plans start from the reference schedule; plans keep 0.2 m
%     above each customer floor for the fitted model's pressure error.
% (b) Cost per m3 by source and pump combination: EPANET snapshots of every station combination
%     with both tanks 85% full (the pump plans' start level), and at 50% and 90% for the effect of
%     level. Pump power uses the model's efficiency curve where one applies to the pump (NPL_2-Eff:
%     the six NPL2 pumps, head curve NPL_2) and the model's global 75% otherwise: the NPL3 (NPL3-115)
%     and TM Pond (TM_Pond) head curves have no efficiency curve, and DK_1-Eff and BPK_Eff belong to
%     the DK_1 and BPK head curves, which no pump at these stations uses. Part (a) keeps EPANET's 75%
%     for every pump, as optimize_pumps.m does, so its energy figures compare with pump_plans.md.
%
% Scenario: without the placeholder nodes 71 and 678 (488,403 m3/day), flat demand (the model has no
% demand pattern), all pumps available. ASSUMPTION to replace with Eastwater data: weekday TOU tariff
% 4.1839 THB/kWh 09:00-22:00 and 2.6037 off-peak.
% Writes reports/matlab/whatif_storage_sources.md, whatif_storage_kpis.csv, whatif_storage_schedule.csv,
% whatif_station_cost.csv, whatif_combination_cost.csv and whatif_storage_sources.png.
% Run time about an hour (the 1x MILPs stop at the 300 s limit). Optional, set before run(): scales
% (default [1 2 5 10]), levelGrid (snapshot levels, default 30-95% full), outDir (default reports/matlab),
% e.g. a quick test: matlab -batch "scales=10; levelGrid=[0.4 0.6 0.8 0.95]; outDir=tempdir; run('matlab/whatif_storage_sources.m')"

root = fileparts(fileparts(mfilename('fullpath')));
addpath(fileparts(mfilename('fullpath')));
if ~exist('scales', 'var'), scales = [1 2 5 10]; end
if ~exist('levelGrid', 'var'), levelGrid = 0.30:0.05:0.95; end
if ~exist('outDir', 'var'), outDir = fullfile(root, 'reports', 'matlab'); end
if ~isfolder(outDir), mkdir(outDir); end
inp = fullfile(fileparts(root), 'Demand-2023 v20RY to MTP new TM2P.inp');
clock0 = tic;

% Illustrative weekday TOU tariff, THB/kWh (peak 09:00-22:00). ASSUMPTION: replace with actual.
cfg.peak = 4.1839;
cfg.offPeak = 2.6037;
cfg.tariff = cfg.offPeak * ones(24, 1);
cfg.tariff(10:22) = cfg.peak;
cfg.hours = 24;
cfg.scales = scales(:)';
cfg.maxRounds = 6;
cfg.reserve = 0.10;            % tank reserve EPANET must show, fraction of range (as Plan A)
cfg.pressureMargin = 0.2;      % plans keep 0.2 m above each customer floor for the fitted model's error
cfg.planMax = 0.90;            % plans stay below 90% full, clear of EPANET's full-tank shut-off
cfg.refLevel = 0.85;           % start level of optimize_pumps.m; reference level for part (b)
cfg.grid = levelGrid;          % tank levels (fraction of range) solved for the level-aware model
cfg.stations = ["NPL2-", "NPL3-", "TM_Pond_"];
cfg.stationNames = ["NPL2", "NPL3", "TM Pond"];
cfg.effCurve = ["NPL_2-Eff", "", ""];   % efficiency curve per station; "" = model's global 75%
cfg.zeroNodes = ["71"; "678"];
% The third plan repeats the lowest-cost plan at the largest size with optimize_pumps.m's start rule
% (85% full at midnight), to show what that rule alone would cost
plans = struct('key', {"reference", "lowest_cost", "lowest_cost_85_midnight"}, ...
               'name', {"Reference (lowest energy)", "Lowest cost (tariff-aware)", "Lowest cost, starting 85% full at midnight"}, ...
               'tariffAware', {false, true, true}, 'fixStart', {NaN, NaN, cfg.refLevel}, ...
               'onlyScale', {NaN, NaN, max(cfg.scales)});

% Customer floor = 10 m, or the model's own minimum where it is lower (as optimize_pumps.m)
[d, c] = load_network(inp);
asIs = validate_plan(d, struct('hours', cfg.hours, 'tariff', cfg.tariff), struct('targetPressure', 10));
clear c
floorOf = dictionary(asIs.customers.node, min(10, asIs.customers.min_pressure_m));

% The scenario network
[d, c] = loadScenario(inp, cfg.zeroNodes, 1, []);
pumps = d.getLinkPumpIndex;
pumpNames = string(d.getLinkNameID(pumps));
station = zeros(numel(pumps), 1);
for s = 1:3
    station(startsWith(pumpNames, cfg.stations(s))) = s;
end
tanks = d.getNodeTankIndex;
tankNames = string(d.getNodeNameID(tanks));
nT = numel(tanks);
assert(nT == 2, 'The level-aware model is written for the two head tanks');
lvlMin = d.getNodeTankMinimumWaterLevel;
lvlMax = d.getNodeTankMaximumWaterLevel;
span = lvlMax - lvlMin;
area = pi * d.getNodeTankDiameter.^2 / 4;
junc = d.getNodeJunctionIndex;
bd = d.getNodeBaseDemands;
cust = junc(bd{1}(junc) > 0);
custNames = string(d.getNodeNameID(cust));
floorP = reshape(floorOf(custNames(:)), 1, []);      % row, customer order
demand = sum(bd{1}(cust));
linkEnds = double(d.py.getLinkNodesIndex());         % [from to] node of every link
net = struct('pumps', pumps, 'station', station, 'tanks', tanks, 'cust', cust, ...
             'pumpEnds', linkEnds(pumps, :), 'lvlMin', lvlMin, 'lvlMax', lvlMax, 'area', area);

% Pump curves and sources from the .inp text
inpLines = readlines(inp);
headCurve = strings(1, numel(pumps));
for r = inpSection(inpLines, "PUMPS")
    k = find(pumpNames == r{1}(1));
    if ~isempty(k), headCurve(k) = r{1}(find(upper(r{1}) == "HEAD", 1) + 1); end
end
maxFlow = zeros(1, numel(pumps));                    % end of each head curve, CMD
for k = 1:numel(pumps)
    xy = readCurve(inpLines, headCurve(k));
    if size(xy, 1) == 1, maxFlow(k) = 2 * xy(1, 1); else, maxFlow(k) = xy(end, 1); end   % EPANET's 1-point rule
end
effXY = cell(1, 3);
for s = 1:3
    if cfg.effCurve(s) ~= "", effXY{s} = readCurve(inpLines, cfg.effCurve(s)); end
end
src = stationSources(inpLines, d, station, net.pumpEnds);

% 1. Every station combination as an EPANET snapshot at 50%, 85% and 90% full (part b), then, for
%    part (a), every combination with a TM Pond count that can run, on a grid of levels of both tanks
fprintf('Snapshots...\n');
d.setTimeSimulationDuration(0);
[n2, n3, nt] = ndgrid(0:6, 0:6, 0:6);
combos = [n2(:), n3(:), nt(:)];
partLevels = [0.50, cfg.refLevel, cfg.planMax];
Sb = cell(1, numel(partLevels));
for i = 1:numel(partLevels)
    Sb{i} = snapshots(d, combos, partLevels(i) * ones(1, nT), net);
end
okRef = validCode(Sb{2}.code);
maxTM = max(combos(okRef, 3));
gridCombos = combos(combos(:, 3) <= maxTM, :);
[g1, g2] = ndgrid(cfg.grid, cfg.grid);
lv = [g1(:), g2(:)];
G = struct('C', [], 'F', [], 'code', [], 'Q', [], 'P', [], 'custP', []);
for f = 1:size(lv, 1)
    S = snapshots(d, gridCombos, lv(f, :), net);
    G.C = [G.C; gridCombos];
    G.F = [G.F; repmat(lv(f, :), size(gridCombos, 1), 1)];
    G.code = [G.code; S.code];
    G.Q = [G.Q; S.Q];
    G.P = [G.P; sum(S.P, 2)];
    G.custP = [G.custP; S.custP];
end
clear c
fprintf('  %d + %d snapshots, %.0f s\n', numel(partLevels) * size(combos, 1), size(G.C, 1), toc(clock0));
M = fitLevelModel(G, cfg.grid, floorP);
fprintf('  fit: tank inflow within %s m3/h, power within %.1f kW, pressure within %.2f m\n', ...
    strjoin(compose("%.0f", M.maxErrQ), " / "), M.maxErrP, M.maxErrC);

% 2. Part (b): cost per m3 by station and by combination
[stationCost, comboCost] = costTables(Sb, partLevels, combos, cfg, net, effXY, floorP, src);
writetable(stationCost, fullfile(outDir, 'whatif_station_cost.csv'));
writetable(comboCost, fullfile(outDir, 'whatif_combination_cost.csv'));

% 3. Part (a): reference and lowest-cost plan for each storage size
runs = struct('scale', {}, 'plan', {}, 'best', {}, 'converged', {}, 'rounds', {}, 'log', {});
for k = cfg.scales
    warm = [];
    for ip = 1:numel(plans)
        if ~isnan(plans(ip).onlyScale) && k ~= plans(ip).onlyScale, continue; end
        out = optimisePlan(inp, cfg, M, net, k, plans(ip), floorP, maxFlow, warm);
        out.scale = k;
        out.plan = ip;
        runs(end+1) = out; %#ok<SAGROW>
        % The tariff-aware plans start from the reference schedule, so they can only improve on it
        if ip == 1 && ~isempty(out.best), warm = out.best.sol; end
        fprintf('%gx %s: %s after %d round(s), %.0f s so far\n', k, plans(ip).name, ...
            ifelse(out.converged, "passes", "does not pass"), out.rounds, toc(clock0));
    end
end

% 4. Tables, figure and report
[kpis, sched] = storageTables(runs, plans, cfg, net, demand, tankNames);
writetable(kpis, fullfile(outDir, 'whatif_storage_kpis.csv'));
writetable(sched, fullfile(outDir, 'whatif_storage_schedule.csv'));
plotWhatIf(fullfile(outDir, 'whatif_storage_sources.png'), runs, kpis, stationCost, cfg, net);
prev = readPrevious(fullfile(root, 'reports', 'matlab', 'pump_plans_kpis.csv'));
L = report(cfg, plans, runs, kpis, stationCost, comboCost, M, net, demand, tankNames, prev, toc(clock0));
writelines(L, fullfile(outDir, 'whatif_storage_sources.md'));
fprintf('%s\n', L);

%% ------------------------------------------------------------------ network and snapshots

function [d, c] = loadScenario(inp, zeroNodes, scale, level0)
% The model without the placeholder nodes; head tanks scale x their volume (diameter x sqrt(scale),
% levels kept); tanks start at level0 (fraction of range, [] = model's levels)
[d, c] = load_network(inp);
for n = zeroNodes(:)'
    d.setNodeBaseDemands(d.getNodeIndex(char(n)), 0);
end
if scale ~= 1
    d.py.setNodeTankDiameter(py.list(num2cell(d.getNodeTankDiameter * sqrt(scale))));
end
if ~isempty(level0)
    lmin = d.getNodeTankMinimumWaterLevel;
    d.setNodeTankInitialLevel(lmin + level0 .* (d.getNodeTankMaximumWaterLevel - lmin));
end
end

function S = snapshots(d, combos, level, net)
% Each combination solved as an EPANET snapshot (duration 0) with the tanks at level (fraction of range)
d.setNodeTankInitialLevel(net.lvlMin + level .* (net.lvlMax - net.lvlMin));
n = size(combos, 1);
np = numel(net.pumps);
S = struct('code', nan(n, 1), 'P', nan(n, 3), 'Qst', nan(n, 3), 'Q', nan(n, numel(net.tanks)), ...
           'custP', nan(n, numel(net.cust)), 'q', nan(n, np), 'head', nan(n, np), 'e', nan(n, np));
for k = 1:n
    d.setLinkInitialStatus(net.pumps, pumpsFor(combos(k, :), net.station)');
    d.openHydraulicAnalysis;
    d.initializeHydraulicAnalysis(0);
    d.runHydraulicAnalysis;
    S.code(k) = d.Errcode;
    p = d.getNodePressure;
    hd = d.getNodeHydraulicHead;
    dem = d.getNodeActualDemand;
    e = d.getLinkEnergy(net.pumps);
    q = d.getLinkFlows(net.pumps);
    for s = 1:3
        S.P(k, s) = sum(e(net.station == s));
        S.Qst(k, s) = sum(q(net.station == s)) / 24;
    end
    S.Q(k, :) = dem(net.tanks) / 24;               % net inflow to each tank, m3/h
    S.custP(k, :) = p(net.cust);
    S.q(k, :) = q;                                 % CMD
    S.head(k, :) = hd(net.pumpEnds(:, 2)) - hd(net.pumpEnds(:, 1));
    S.e(k, :) = e;                                 % kW at the model's 75%
    d.closeHydraulicAnalysis;
end
end

function ok = validCode(code)
% Hydraulically valid: balanced, connected and every pump on its curve (code 4 = a pump cannot
% deliver the head or runs beyond the end of its curve)
ok = ~(code == 1 | code == 3 | code == 4 | code > 100);
end

function on = pumpsFor(n, station)
% First n(s) pumps of each station switched on (pumps in a station share one curve)
on = zeros(numel(station), 1);
for s = 1:numel(n)
    members = find(station == s);
    on(members(1:n(s))) = 1;
end
end

%% ------------------------------------------------------------------ level-aware model

function X = levelFeatures(C, F)
% One term per station pump count, each linear in the two tank levels: [1, l1, l2] x one-hot
n = size(C, 1);
X = zeros(n, 63);
for s = 1:3
    col = (s - 1) * 7 + C(:, s) + 1;
    X(sub2ind([n 63], (1:n)', col)) = 1;
    X(sub2ind([n 63], (1:n)', 21 + col)) = F(:, 1);
    X(sub2ind([n 63], (1:n)', 42 + col)) = F(:, 2);
end
end

function M = fitLevelModel(G, grid, floorP)
% Tank inflows, total power and customer pressures as a sum of station terms linear in the levels,
% fitted on the valid grid snapshots. Responses: [inflow tank 1, inflow tank 2, power, pressures].
ok = validCode(G.code);
% Lowest level of each tank at which some valid combination keeps every customer above its floor
% (any level of the other tank), with any TM Pond pumps and with none
meets = ok & all(G.custP >= floorP, 2);
M.pressureLow = [min(G.F(meets, 1)), min(G.F(meets, 2))];
M.pressureLowNoTM = [min(G.F(meets & G.C(:, 3) == 0, 1)), min(G.F(meets & G.C(:, 3) == 0, 2))];
X = levelFeatures(G.C(ok, :), G.F(ok, :));
Y = [G.Q(ok, :), G.P(ok), G.custP(ok, :)];
M.B = lsqminnorm(X, Y);
err = abs(X * M.B - Y);
M.maxErrQ = max(err(:, 1:2), [], 1);
M.rmsErrQ = sqrt(mean(err(:, 1:2).^2, 1));
M.maxErrP = max(err(:, 3));
M.maxErrC = max(err(:, 4:end), [], 'all');
M.bandLo = min(grid);
M.bandHi = max(grid);
M.nValid = nnz(ok);
M.nSnap = numel(ok);
% How much level matters: the most pumping, with both tanks at the lowest and the highest grid level
cmax = max(G.C, [], 1);
rlo = find(all(G.C == cmax, 2) & all(G.F == M.bandLo, 2), 1);
rhi = find(all(G.C == cmax, 2) & all(G.F == M.bandHi, 2), 1);
M.stats = struct('combo', cmax, 'Qlo', G.Q(rlo, :), 'Qhi', G.Q(rhi, :), 'Plo', min(G.custP(rlo, :)), ...
                 'Phi', min(G.custP(rhi, :)));
% Pump counts allowed, and the level each count needs to stay on its curve: count j of station s is
% valid at the grid points where any combination with it is valid; this must be a level threshold
% on one tank (NPL2 pumps: their own tank NPL2_HT)
lv = unique(G.F, 'rows');
M.allowed = cell(1, 3);
M.theta = zeros(3, 7, 2);
for s = 1:3
    for j = 0:6
        v = false(size(lv, 1), 1);
        for f = 1:size(lv, 1)
            rows = G.C(:, s) == j & all(G.F == lv(f, :), 2);
            v(f) = any(ok(rows));
        end
        if ~any(v), continue; end
        M.allowed{s}(end+1) = j;
        if all(v), continue; end
        found = false;
        for m = 1:2
            th = min(lv(v, m));
            if isequal(v, lv(:, m) >= th - 1e-9)
                M.theta(s, j + 1, m) = th;
                found = true;
                break
            end
        end
        assert(found, 'Validity of %d pumps at station %d is not a level threshold on one tank', j, s);
    end
end
end

function [sol, exitflag, gap] = solveLevelMilp(M, objTariff, tariff, vol, lo, hi, endExtra, floorPlan, pad, start0, warm)
% y(h,s,j) = 1 when station s runs j pumps in hour h. lam(m,t): level of tank m at time t (fraction of
% its range), t = 0..H; the start level is free (or start0) and the day must end at least as full plus
% endExtra. z(h,s,j,m) = y(h,s,j) * lam(m,h-1) is exact because one j is chosen per station-hour:
% sum_j z = lam and lo*y <= z <= hi*y. Tank inflow, power and customer pressure in hour h are linear in
% y and z, so tanks are stepped with start-of-hour flows, as EPANET does with 1 h steps. The binaries
% are u(h,s,k) = "at least the k-th allowed count" (y = u_k - u_k+1): same LP bound as binary y, but
% branching splits the counts into higher and lower, which solves several times faster here.
% warm (counts, level) is a known schedule to start the search from, used when it is feasible.
H = numel(objTariff);
nT = numel(vol);
vars = zeros(0, 3);
for h = 1:H
    for s = 1:3
        for j = M.allowed{s}
            th = reshape(M.theta(s, j + 1, :), 1, []);
            if any(th > 0 & th + pad > hi), continue; end     % valid only above the plan ceiling
            vars(end+1, :) = [h, s, j]; %#ok<AGROW>
        end
    end
end
nx = size(vars, 1);
col = (vars(:, 2) - 1) * 7 + vars(:, 3) + 1;
ca = M.B(col, :);
cb = {M.B(21 + col, :), M.B(42 + col, :)};
nl = nT * (H + 1);
li = @(m, t) nx + (m - 1) * (H + 1) + t + 1;
zi = @(i, m) nx + nl + (m - 1) * nx + i;
u0 = nx + nl + nT * nx;                              % u follow; one fewer than counts per station-hour
nu = nx - 3 * H;
nv = u0 + nu;
rP = nT + 1;                                         % response columns: inflows, power, pressures
rC = nT + 1 + (1:numel(floorPlan));

f = zeros(nv, 1);
w = objTariff(vars(:, 1));
f(1:nx) = w .* ca(:, rP);
for m = 1:nT
    f(zi((1:nx)', m)) = w .* cb{m}(:, rP);
end
[Ie, Je, Ve, beq, Ii, Ji, Vi, bin] = deal([]);
re = 0;
ri = 0;
uc = u0;
for h = 1:H
    hx = find(vars(:, 1) == h);
    for s = 1:3
        sx = hx(vars(hx, 2) == s);                   % counts in increasing order
        K = numel(sx) - 1;
        uk = uc + (1:K)';
        uc = uc + K;
        re = re + 1;                                 % one count per station-hour: y_1 = 1 - u_1, ...
        Ie = [Ie; re; re + 0 * uk(1:min(K, 1))]; Je = [Je; sx(1); uk(1:min(K, 1))]; %#ok<AGROW>
        Ve = [Ve; 1; 1 + 0 * uk(1:min(K, 1))]; beq(re, 1) = 1; %#ok<AGROW>
        for q = 1:K                                  % ... y_q+1 = u_q - u_q+1, and y_K+1 = u_K
            re = re + 1;
            if q < K
                Ie = [Ie; re; re; re]; Je = [Je; sx(q + 1); uk(q); uk(q + 1)]; Ve = [Ve; 1; -1; 1]; %#ok<AGROW>
            else
                Ie = [Ie; re; re]; Je = [Je; sx(q + 1); uk(q)]; Ve = [Ve; 1; -1]; %#ok<AGROW>
            end
            beq(re, 1) = 0;
        end
        for m = 1:nT
            re = re + 1;                             % sum_j z = start-of-hour level
            Ie = [Ie; re + 0 * sx; re]; Je = [Je; zi(sx, m); li(m, h - 1)]; %#ok<AGROW>
            Ve = [Ve; 1 + 0 * sx; -1]; beq(re, 1) = 0; %#ok<AGROW>
            th = reshape(M.theta(s, vars(sx, 3) + 1, m), [], 1);
            th(th > 0) = th(th > 0) + pad;
            if any(th > lo(m))                       % pump-curve limit: level >= the count's threshold
                ri = ri + 1;
                Ii = [Ii; ri + 0 * sx; ri]; Ji = [Ji; sx; li(m, h - 1)]; Vi = [Vi; th; -1]; bin(ri, 1) = 0; %#ok<AGROW>
            end
        end
    end
    for m = 1:nT                                     % tank balance over the hour, in fractions of range
        re = re + 1;
        Ie = [Ie; re; re; repmat(re, 3 * numel(hx), 1)]; %#ok<AGROW>
        Je = [Je; li(m, h); li(m, h - 1); hx; zi(hx, 1); zi(hx, 2)]; %#ok<AGROW>
        Ve = [Ve; 1; -1; -[ca(hx, m); cb{1}(hx, m); cb{2}(hx, m)] / vol(m)]; %#ok<AGROW>
        beq(re, 1) = 0;
    end
    for c = 1:numel(rC)                              % customer pressure floors
        ri = ri + 1;
        Ii = [Ii; repmat(ri, 3 * numel(hx), 1)]; Ji = [Ji; hx; zi(hx, 1); zi(hx, 2)]; %#ok<AGROW>
        Vi = [Vi; -[ca(hx, rC(c)); cb{1}(hx, rC(c)); cb{2}(hx, rC(c))]]; bin(ri, 1) = -floorPlan(c); %#ok<AGROW>
    end
end
idx = (1:nx)';
for m = 1:nT                                         % z = y * level: lo*y <= z <= hi*y
    Ii = [Ii; ri + idx; ri + idx; ri + nx + idx; ri + nx + idx]; %#ok<AGROW>
    Ji = [Ji; zi(idx, m); idx; zi(idx, m); idx]; %#ok<AGROW>
    Vi = [Vi; ones(nx, 1); -hi(m) * ones(nx, 1); -ones(nx, 1); lo(m) * ones(nx, 1)]; %#ok<AGROW>
    bin(ri + (1:2 * nx), 1) = 0;
    ri = ri + 2 * nx;
end
for m = 1:nT                                         % repeatable day
    ri = ri + 1;
    Ii = [Ii; ri; ri]; Ji = [Ji; li(m, 0); li(m, H)]; Vi = [Vi; 1; -1]; bin(ri, 1) = -endExtra(m); %#ok<AGROW>
end
Aeq = sparse(Ie, Je, Ve, re, nv);
A = sparse(Ii, Ji, Vi, ri, nv);
lb = zeros(nv, 1);
ub = ones(nv, 1);
for m = 1:nT
    lb(li(m, 0:H)) = lo(m);
    ub(li(m, 0:H)) = hi(m);
    ub(zi(idx, m)) = hi(m);
    if ~isnan(start0), lb(li(m, 0)) = start0; ub(li(m, 0)) = start0; end
end
% Start point from a known schedule: y from its counts, z = y * level, u = "at least the k-th count"
x0 = [];
if ~isempty(warm)
    x0 = zeros(nv, 1);
    for i = 1:nx
        x0(i) = warm.counts(vars(i, 1), vars(i, 2)) == vars(i, 3);
    end
    for m = 1:nT
        x0(li(m, 0:H)) = warm.level(m, :);
        x0(zi(idx, m)) = x0(idx) .* warm.level(m, vars(:, 1))';
    end
    uc = u0;
    for h = 1:H
        for s = 1:3
            sx = find(vars(:, 1) == h & vars(:, 2) == s);
            p = find(x0(sx) == 1, 1);
            if isempty(p), x0 = []; break; end   % the schedule uses a count not allowed here
            x0(uc + (1:numel(sx) - 1)) = (1:numel(sx) - 1)' < p;
            uc = uc + numel(sx) - 1;
        end
        if isempty(x0), break; end
    end
    if ~isempty(x0) && (any(A * x0 > bin + 1e-6) || any(abs(Aeq * x0 - beq) > 1e-6) || any(x0 < lb - 1e-9) || any(x0 > ub + 1e-9))
        x0 = [];                                     % infeasible under this round's limits
    end
end
% Many schedules cost almost the same, so stop at a 0.5% optimality gap; the time limit is a safety net
opts = optimoptions('intlinprog', 'Display', 'off', 'MaxTime', 300, 'RelativeGapTolerance', 5e-3);
[x, ~, exitflag, out] = intlinprog(f, u0 + (1:nu), A, bin, Aeq, beq, lb, ub, x0, opts);
gap = out.relativegap;
sol = struct('counts', [], 'level', [], 'power', [], 'energy', NaN, 'cost', NaN);
if exitflag <= 0, return; end
y = round(x(1:nx));
sol.counts = zeros(H, 3);
for i = find(y == 1)'
    sol.counts(vars(i, 1), vars(i, 2)) = vars(i, 3);
end
sol.level = reshape(x(nx + 1:nx + nl), H + 1, nT)';
sol.power = zeros(H, 1);
for h = 1:H
    i = find(vars(:, 1) == h & y == 1);
    sol.power(h) = sum(ca(i, rP) + cb{1}(i, rP) * sol.level(1, h) + cb{2}(i, rP) * sol.level(2, h));
end
sol.energy = sum(sol.power);
sol.cost = tariff' * sol.power;
end

function out = optimisePlan(inp, cfg, M, net, k, plan, floorP, maxFlow, warm)
% Optimise-and-check rounds for one plan at one storage size. EPANET is judged against the fixed spec
% (reserve, customer floors, end level); only the planning margins move between rounds. warm is a
% schedule to start the first search from (the reference, for the lowest-cost plans), or [].
H = cfg.hours;
nT = numel(net.tanks);
span = net.lvlMax - net.lvlMin;
vol = k * net.area .* span;                          % m3 per unit of level fraction
objTariff = cfg.tariff;
if ~plan.tariffAware, objTariff(:) = mean(cfg.tariff); end      % minimise energy only
lo = max(cfg.reserve, M.bandLo) * ones(1, nT);
hi = min(cfg.planMax, M.bandHi) * ones(1, nT);
margin = cfg.pressureMargin * ones(size(floorP));
endExtra = zeros(1, nT);
pad = 0;
out = struct('scale', k, 'plan', 0, 'best', [], 'converged', false, 'rounds', 0, 'log', strings(0, 1));
for iter = 1:cfg.maxRounds
    t0 = tic;
    [sol, exitflag, gap] = solveLevelMilp(M, objTariff, cfg.tariff, vol, lo, hi, endExtra, floorP + margin, pad, ...
                                          plan.fixStart, warm);
    secs = toc(t0);
    fprintf('  %gx %s round %d: MILP %.1f s, exitflag %d, gap %s\n', k, plan.name, iter, secs, exitflag, gapText(gap));
    out.rounds = iter;
    if exitflag <= 0
        out.log(end+1) = sprintf("round %d: no schedule meets the planning limits", iter);
        break
    end
    on = zeros(H, numel(net.pumps));
    for h = 1:H
        on(h, :) = pumpsFor(sol.counts(h, :), net.station);
    end
    [d, c] = loadScenario(inp, cfg.zeroNodes, k, sol.level(:, 1)');
    R = validate_plan(d, struct('hours', H, 'pumpOn', on, 'tariff', cfg.tariff), ...
                      struct('targetPressure', floorP(:), 'endTankTol', 0.25));
    clear c
    chk = checkPlan(R, on, net, cfg.reserve, floorP, maxFlow);
    out.best = struct('R', R, 'on', on, 'sol', sol, 'gap', gap, 'secs', secs, 'chk', chk, ...
                      'lo', lo, 'margin', margin, 'endExtra', endExtra, 'pad', pad);
    out.log(end+1) = sprintf("round %d: EPANET %s%s", iter, R.status, chk.text);
    if chk.pass
        out.converged = true;
        break
    end
    warm = sol;                                      % used again only if it still meets the new limits
    % Raise only the planning margins: tank floor, pressure margin where a customer fell short,
    % end level, and the pump-curve threshold
    lo(chk.lowTank) = min(lo(chk.lowTank) + 0.05, hi(chk.lowTank) - 0.15);
    margin = margin + chk.lowP .* (chk.shortP + 0.1);
    endExtra = endExtra + chk.lowEnd .* (chk.endShort + 0.01);
    if chk.offCurve, pad = pad + 0.02; end
end
end

function chk = checkPlan(R, on, net, reserve, floorP, maxFlow)
% The fixed spec: tanks above the reserve, customers above their floor, tanks end at least as full as
% they start (0.25 m tolerance), no EPANET failure, and no pump run beyond the end of its curve
span = net.lvlMax - net.lvlMin;
chk.lowTank = R.tanks.min_m' < net.lvlMin + reserve * span - 0.05;
chk.shortP = max(0, floorP - R.customers.min_pressure_m');
chk.lowP = chk.shortP > 0.05;
chk.endShort = max(0, R.tanks.start_m' - R.tanks.end_m') ./ span;
chk.lowEnd = R.tanks.end_m' < R.tanks.start_m' - 0.25;
hourOf = mod(floor(R.steps.time_h + 1e-9), size(on, 1)) + 1;     % the step at 24 h runs hour 1's pumps
flow = R.pumpFlow{:, :};
onNow = on(hourOf, :) > 0;
chk.offCurve = any(onNow & flow > maxFlow * 1.001, 'all');
chk.forcedOff = any(onNow & flow < 1, 'all');
chk.pass = R.status ~= "Fail" && ~any(chk.lowTank) && ~any(chk.lowP) && ~any(chk.lowEnd) && ~chk.offCurve;
items = strings(0, 1);
if any(chk.lowTank), items(end+1) = "tank below reserve"; end
if any(chk.lowP), items(end+1) = sprintf("customer up to %.2f m below floor", max(chk.shortP)); end
if any(chk.lowEnd), items(end+1) = sprintf("tank ends up to %.0f%% of range low", 100 * max(chk.endShort)); end
if chk.offCurve, items(end+1) = "a pump runs beyond its curve"; end
if chk.forcedOff, items(end+1) = "a pump is forced off"; end
if isempty(items), chk.text = ""; else, chk.text = " - " + strjoin(items, ", "); end
end

%% ------------------------------------------------------------------ part (b)

function [st, cb] = costTables(Sb, levels, combos, cfg, net, effXY, floorP, src)
% kWh/m3 and THB/m3 by station pump count, and by station combination. Power with the efficiency curve
% where one applies: EPANET's power at 75% x 0.75 / efficiency at the pump's flow.
iRef = find(levels == cfg.refLevel, 1);
used = cell(size(Sb));
for i = 1:numel(Sb)
    used{i} = Sb{i}.e;
    for s = 1:3
        if isempty(effXY{s}), continue; end
        m = net.station == s;
        q = Sb{i}.q(:, m);
        eta = interp1(effXY{s}(:, 1), effXY{s}(:, 2), min(max(q, effXY{s}(1, 1)), effXY{s}(end, 1))) / 100;
        used{i}(:, m) = Sb{i}.e(:, m) * 0.75 ./ max(eta, 0.01) .* (Sb{i}.e(:, m) > 0);
    end
end
tags = compose("_%02.0f", 100 * levels);
st = table();
for s = 1:3
    members = find(net.station == s);
    for j = 1:6
        r = table(cfg.stationNames(s), src.reservoir(s), src.head(s), src.feeds(s), j, ...
            ifelse(isempty(effXY{s}), "model global 75%", cfg.effCurve(s)), ...
            'VariableNames', {'station', 'source', 'source_head_m', 'feeds', 'pumps', 'efficiency_source'});
        [r.flow_m3h, r.flow_per_pump_cmd, r.head_m, r.efficiency_pct, r.power_kw_model75, r.power_kw, ...
         r.kwh_per_m3_model75] = deal(NaN);
        for i = 1:numel(Sb)
            k = find(validCode(Sb{i}.code) & combos(:, s) == j, 1);   % station terms add up, so any will do
            r.("valid" + tags(i)) = ~isempty(k);
            r.("kwh_per_m3" + tags(i)) = NaN;
            if isempty(k), continue; end
            flow = Sb{i}.Qst(k, s);
            r.("kwh_per_m3" + tags(i)) = sum(used{i}(k, members)) / flow;
            if i == iRef
                r.flow_m3h = flow;
                r.flow_per_pump_cmd = Sb{i}.q(k, members(1));
                r.head_m = Sb{i}.head(k, members(1));
                r.efficiency_pct = 75 * Sb{i}.e(k, members(1)) / used{i}(k, members(1));
                r.power_kw_model75 = sum(Sb{i}.e(k, members));
                r.power_kw = sum(used{i}(k, members));
                r.kwh_per_m3_model75 = r.power_kw_model75 / flow;
            end
        end
        r.thb_per_m3_offpeak = r.("kwh_per_m3" + tags(iRef)) * cfg.offPeak;
        r.thb_per_m3_peak = r.("kwh_per_m3" + tags(iRef)) * cfg.peak;
        st = [st; r]; %#ok<AGROW>
    end
end
st = movevars(st, ["valid" + tags(iRef), "kwh_per_m3" + tags(iRef), "thb_per_m3_offpeak", "thb_per_m3_peak"], ...
              'After', 'kwh_per_m3_model75');
% Every valid combination at the reference level
S = Sb{iRef};
ok = validCode(S.code) & sum(combos, 2) > 0;
k = find(ok);
flow = sum(S.Qst(k, :), 2);
power = sum(used{iRef}(k, :), 2);
margin = min(S.custP(k, :) - floorP, [], 2);
cb = table(combos(k, 1), combos(k, 2), combos(k, 3), S.Qst(k, 1), S.Qst(k, 2), S.Qst(k, 3), flow, ...
    sum(S.e(k, :), 2), power, sum(S.e(k, :), 2) ./ flow, power ./ flow, power ./ flow * cfg.offPeak, ...
    power ./ flow * cfg.peak, S.Q(k, 1), S.Q(k, 2), margin, margin >= 0 & all(S.Q(k, :) >= 0, 2), ...
    'VariableNames', {'npl2_pumps', 'npl3_pumps', 'tm_pond_pumps', 'npl2_flow_m3h', 'npl3_flow_m3h', ...
    'tm_pond_flow_m3h', 'total_flow_m3h', 'power_kw_model75', 'power_kw', 'kwh_per_m3_model75', 'kwh_per_m3', ...
    'thb_per_m3_offpeak', 'thb_per_m3_peak', 'npl2_ht_net_inflow_m3h', 'npl3_ht_net_inflow_m3h', ...
    'lowest_customer_margin_m', 'can_run_all_day'});
cb = sortrows(cb, 'kwh_per_m3');
end

function src = stationSources(L, d, station, pumpEnds)
% The reservoir each station draws from and the tanks its discharge reaches, traced through open pipes
% and valves (not through pumps)
closed = strings(0, 1);
for r = inpSection(L, "STATUS")
    if upper(r{1}(2)) == "CLOSED", closed(end+1) = r{1}(1); end %#ok<AGROW>
end
e = strings(0, 2);
for sec = ["PIPES", "VALVES"]
    for r = inpSection(L, sec)
        t = r{1};
        isClosed = any(closed == t(1)) || (sec == "PIPES" && numel(t) >= 8 && upper(t(8)) == "CLOSED");
        if ~isClosed, e(end+1, :) = t(2:3); end %#ok<AGROW>
    end
end
g = graph(e(:, 1), e(:, 2));
ids = string(d.getNodeNameID);
resNames = ids(setdiff(1:numel(ids), [d.getNodeJunctionIndex, d.getNodeTankIndex]));
tankNames = ids(d.getNodeTankIndex);
elev = d.getNodeElevations;
% The tanks split the network: a station feeds the tanks that border the part its discharge reaches
gt = rmnode(g, tankNames(findnode(g, tankNames) > 0));
comp = conncomp(gt);
compOf = @(names) comp(nonzeros(findnode(gt, names)));
src = struct('reservoir', strings(1, 3), 'head', nan(1, 3), 'feeds', strings(1, 3));
for s = 1:3
    k = find(station == s, 1);
    up = compOf(ids(pumpEnds(k, 1)));
    dn = compOf(ids(pumpEnds(k, 2)));
    r = resNames(arrayfun(@(n) findnode(gt, n) > 0 && compOf(n) == up, resNames));
    t = tankNames(arrayfun(@(n) any(compOf(string(neighbors(g, n))) == dn), tankNames));
    src.reservoir(s) = strjoin(r, " + ");
    src.head(s) = round(elev(d.getNodeIndex(char(r(1)))), 2);
    src.feeds(s) = strjoin(t, " + ");
end
end

function rows = inpSection(L, name)
% Data lines of one .inp section, split into tokens (comments dropped)
rows = {};
in = false;
for i = 1:numel(L)
    t = strtrim(extractBefore(L(i) + ";", ";"));
    if startsWith(t, "[")
        in = upper(t) == "[" + upper(name) + "]";
    elseif in && t ~= ""
        rows{end+1} = split(t)'; %#ok<AGROW>
    end
end
end

function xy = readCurve(L, id)
xy = zeros(0, 2);
for r = inpSection(L, "CURVES")
    if r{1}(1) == id, xy(end+1, :) = double(r{1}(2:3)); end %#ok<AGROW>
end
end

%% ------------------------------------------------------------------ results

function [kp, sched] = storageTables(runs, plans, cfg, net, demand, tankNames)
% One KPI row per storage size and plan (EPANET figures; "model_" = the MILP's own estimate)
span = net.lvlMax - net.lvlMin;
usable = sum(net.area .* span);
tags = lower(erase(tankNames, "_"));
lvlNames = [tags(1) + ["_start_pct", "_min_pct", "_max_pct", "_end_pct"], ...
            tags(2) + ["_start_pct", "_min_pct", "_max_pct", "_end_pct"]];
names = ["storage_scale", "usable_volume_m3", "storage_hours", "plan", "passes", "status", "rounds", ...
         "energy_kwh", "cost_thb", "kwh_per_m3", "thb_per_m3", "saving_pct", "saving_thb_per_day", ...
         "saving_vs_today_pct", "model_energy_kwh", "model_cost_thb", "model_saving_pct", "offpeak_energy_pct", ...
         "min_customer_pressure_m", "pump_starts", "peak_pumps_avg", "milp_gap_pct", lvlNames, "notes"];
kp = table();
sched = table();
for r = runs
    k = r.scale;
    b = r.best;
    v = num2cell(nan(1, numel(names)));
    row = cell2struct(v, cellstr(names), 2);
    row.storage_scale = k;
    row.usable_volume_m3 = k * usable;
    row.storage_hours = k * usable / (demand / 24);
    row.plan = plans(r.plan).name;
    row.passes = r.converged;
    row.rounds = r.rounds;
    row.status = "no schedule";
    row.notes = strjoin(r.log, "; ");
    if ~isempty(b)
        R = b.R;
        row.status = R.status;
        row.energy_kwh = R.kpi.energy_kwh;
        row.cost_thb = R.kpi.cost_thb;
        row.kwh_per_m3 = R.kpi.kwh_per_m3;
        row.thb_per_m3 = R.kpi.thb_per_m3;
        row.model_energy_kwh = b.sol.energy;
        row.model_cost_thb = b.sol.cost;
        hourOf = min(floor(R.steps.time_h) + 1, cfg.hours);
        e = R.steps.pump_power_kw .* R.steps.duration_h;
        row.offpeak_energy_pct = 100 * sum(e(cfg.tariff(hourOf) == cfg.offPeak)) / sum(e);
        row.min_customer_pressure_m = R.kpi.min_customer_pressure_m;
        row.pump_starts = sum(sum(max(diff(b.on, 1, 1), 0)));
        row.peak_pumps_avg = mean(sum(b.on(10:22, :), 2));
        row.milp_gap_pct = 100 * b.gap;
        lvl = 100 * ([R.tanks.start_m'; R.tanks.min_m'; R.tanks.max_m'; R.tanks.end_m'] - net.lvlMin) ./ span;
        for i = 1:numel(lvlNames)
            row.(lvlNames(i)) = lvl(i);              % column-major: tank 1's four values, then tank 2's
        end
        sched = [sched; scheduleTable(k, plans(r.plan).name, b.on, net, cfg.tariff, R, tags)]; %#ok<AGROW>
    end
    kp = [kp; struct2table(row)]; %#ok<AGROW>
end
% Savings, only when both plans pass: each tariff-aware plan against the reference at the same size
% (the time-of-use saving), and every plan against the reference with today's tanks (1x)
j1 = find(kp.plan == plans(1).name & kp.storage_scale == 1, 1);
for i = 1:height(kp)
    j = find(kp.plan == plans(1).name & kp.storage_scale == kp.storage_scale(i), 1);
    if i ~= j && ~isempty(j)
        kp.model_saving_pct(i) = 100 * (1 - kp.model_cost_thb(i) / kp.model_cost_thb(j));
        if kp.passes(i) && kp.passes(j)
            kp.saving_pct(i) = 100 * (1 - kp.cost_thb(i) / kp.cost_thb(j));
            kp.saving_thb_per_day(i) = kp.cost_thb(j) - kp.cost_thb(i);
        end
    end
    if ~isempty(j1) && kp.passes(i) && kp.passes(j1)
        kp.saving_vs_today_pct(i) = 100 * (1 - kp.cost_thb(i) / kp.cost_thb(j1));
    end
end
end

function t = scheduleTable(k, plan, on, net, tariff, R, tags)
hours = size(on, 1);
counts = zeros(hours, 3);
for s = 1:3, counts(:, s) = sum(on(:, net.station == s), 2); end
span = net.lvlMax - net.lvlMin;
lvl = nan(hours, 2);
for h = 0:hours - 1
    i = find(abs(R.steps.time_h - h) < 1e-6, 1);
    if ~isempty(i), lvl(h + 1, :) = 100 * (R.tankLevels(i, :) - net.lvlMin) ./ span; end
end
t = table(repmat(k, hours, 1), repmat(plan, hours, 1), (0:hours - 1)', counts(:, 1), counts(:, 2), counts(:, 3), ...
    tariff, lvl(:, 1), lvl(:, 2), 'VariableNames', {'storage_scale', 'schedule', 'hour', 'npl2_pumps', ...
    'npl3_pumps', 'tm_pond_pumps', 'tariff_thb_per_kwh', char(tags(1) + "_start_pct"), char(tags(2) + "_start_pct")});
end

function prev = readPrevious(file)
% The earlier optimizer's reference for the same scenario (pump_plans.md), for comparison only
prev = struct('found', false);
if ~isfile(file), return; end
t = readtable(file, 'TextType', 'string');
i = find(t.scenario == "Without placeholder nodes 71 and 678" & startsWith(t.schedule, "Reference"), 1);
if isempty(i), return; end
prev = struct('found', true, 'energy_kwh', t.energy_kwh(i), 'cost_thb', t.cost_thb(i), 'kwh_per_m3', t.kwh_per_m3(i));
end

function plotWhatIf(file, runs, kp, st, cfg, net)
% Light theme, palette from the project's chart guidance: one series = one hue, ordered storage sizes
% on a single-hue ramp, three stations in categorical order
ink = [11 11 11] / 255; ink2 = [82 81 78] / 255; grid = [225 224 217] / 255; surface = [252 252 251] / 255;
blue = [42 120 214] / 255;
orange = [235 104 52] / 255;
ramp = [134 182 239; 57 135 229; 28 92 171; 13 54 107] / 255;
cat3 = [42 120 214; 235 104 52; 27 175 122] / 255;
fig = figure('Visible', 'off', 'Position', [100 100 1500 470], 'Color', surface);
theme(fig, 'light');
tl = tiledlayout(fig, 1, 3, 'TileSpacing', 'loose', 'Padding', 'compact');
style = @(ax) set(ax, 'Color', surface, 'XColor', ink2, 'YColor', ink2, 'GridColor', grid, 'GridAlpha', 1, ...
                  'FontSize', 10, 'Box', 'off', 'TickDir', 'out');
% 1. Saving against storage size: time-of-use part, and total against today's lowest-energy plan
ax = nexttile(tl);
lc = kp(kp.plan == "Lowest cost (tariff-aware)", :);
x = 1:height(lc);
sv = [lc.saving_pct, lc.saving_vs_today_pct];
sv(lc.storage_scale == 1, 2) = NaN;                  % today's tanks: the total is the time-of-use saving
hb = bar(ax, x, max(sv, 0), 0.7, 'grouped', 'EdgeColor', 'none');
hb(1).FaceColor = blue;
hb(2).FaceColor = orange;
hold(ax, 'on');
yl = max(1, max([sv(:); 0], [], 'omitnan') * 1.3);
for sr = 1:2
    xe = hb(sr).XEndPoints;
    for i = x
        if isnan(sv(i, sr))
            if lc.storage_scale(i) == 1 && sr == 2, continue; end
            txt = "n/a";
        else
            txt = sprintf('%.1f%%', sv(i, sr));
        end
        text(ax, xe(i), max(sv(i, sr), 0) + 0.02 * yl, txt, 'HorizontalAlignment', 'center', ...
             'VerticalAlignment', 'bottom', 'Color', ink, 'FontSize', 9);
    end
end
labels = compose("%g" + char(215) + "\\newline%s m^3", lc.storage_scale, fmtNum(lc.usable_volume_m3));
set(ax, 'XTick', x, 'XTickLabel', labels, 'TickLabelInterpreter', 'tex');
ylim(ax, [0 yl]); xlim(ax, [0.4 height(lc) + 0.6]);
style(ax); ax.YGrid = 'on';
legend(ax, hb, ["time-of-use (vs lowest-energy plan, same tanks)", "total (vs lowest-energy plan, today's tanks)"], ...
       'Location', 'northwest', 'Box', 'off', 'TextColor', ink2);
xlabel(ax, 'head-tank storage (both tanks, usable volume)');
ylabel(ax, 'saving, % of daily pumping cost');
title(ax, 'Saving of the lowest-cost plan by storage size', 'Color', ink, 'FontWeight', 'bold');
subtitle(ax, 'EPANET-checked plans only; assumed tariff', 'Color', ink2);
% 2. Water stored over the day, lowest-cost plans
ax = nexttile(tl);
xregion(ax, 9, 22, 'FaceColor', [0.94 0.94 0.93]);
hold(ax, 'on');
span = net.lvlMax - net.lvlMin;
w = net.area .* span / sum(net.area .* span);
hs = gobjects(0); names = strings(0);
ks = unique([runs.scale]);
for i = 1:numel(ks)
    r = runs([runs.scale] == ks(i) & [runs.plan] == 2);
    if isempty(r.best), continue; end
    R = r.best.R;
    stored = 100 * ((R.tankLevels - net.lvlMin) ./ span) * w(:);
    hs(end+1) = plot(ax, R.steps.time_h, stored, 'LineWidth', 2, 'Color', ramp(min(i, 4), :)); %#ok<AGROW>
    names(end+1) = sprintf('%g%s storage%s', ks(i), char(215), ifelse(r.converged, "", " (fails check)")); %#ok<AGROW>
end
xlim(ax, [0 cfg.hours]); ylim(ax, [0 100]); set(ax, 'XTick', 0:3:24);
style(ax); ax.YGrid = 'on';
legend(ax, hs, names, 'Location', 'southwest', 'Box', 'off', 'TextColor', ink2);
xlabel(ax, 'hour of day (shaded = peak tariff 09:00-22:00)');
ylabel(ax, 'water stored, % of usable volume');
title(ax, 'Water stored over the day, lowest-cost plans', 'Color', ink, 'FontWeight', 'bold');
subtitle(ax, 'both head tanks together, EPANET 24 h run', 'Color', ink2);
% 3. Cost per m3 by station and pump count
ax = nexttile(tl);
hold(ax, 'on');
hs = gobjects(0);
for s = 1:3
    t = st(st.station == cfg.stationNames(s) & st.valid_85, :);
    hs(s) = plot(ax, t.pumps, t.kwh_per_m3_85, '-o', 'LineWidth', 2, 'Color', cat3(s, :), ...
                 'MarkerFaceColor', cat3(s, :), 'MarkerEdgeColor', surface, 'MarkerSize', 7);
end
xlim(ax, [0.5 6.5]); set(ax, 'XTick', 1:6);
style(ax); ax.YGrid = 'on';
legend(ax, hs, cfg.stationNames, 'Location', 'southeast', 'Box', 'off', 'TextColor', ink2);
xlabel(ax, 'pumps running at the station');
ylabel(ax, 'kWh per m^3 pumped');
title(ax, 'Energy per m^3 by source and pump count', 'Color', ink, 'FontWeight', 'bold');
subtitle(ax, 'tanks 85% full; NPL2 efficiency curve, others 75%', 'Color', ink2);
exportgraphics(fig, file, 'Resolution', 110, 'BackgroundColor', surface);
close(fig);
end

%% ------------------------------------------------------------------ report

function L = report(cfg, plans, runs, kp, st, cb, M, net, demand, tankNames, prev, secs)
span = net.lvlMax - net.lvlMin;
usable = sum(net.area .* span);
lc = kp(kp.plan == plans(2).name, :);
rf = kp(kp.plan == plans(1).name, :);
fx = kp(kp.plan == plans(3).name, :);
m3 = "m" + char(179);
x = char(215);
L = strings(0, 1);
L(end+1) = "# Where could pumping savings come from? Storage what-if and cost per " + m3 + " by source";
L(end+1) = "";
L(end+1) = sprintf("Rayong network model (`Demand-2023 v20RY to MTP new TM2P.inp`) without the placeholder nodes 71 and " + ...
    "678: %s %s/day, flat demand, one weekday, all pumps available. **Assumed tariff** (replace with Eastwater's): " + ...
    "%.4f THB/kWh peak 09:00-22:00, %.4f off-peak. Every plan below is checked in a 24 h EPANET run. " + ...
    "Script: `matlab/whatif_storage_sources.m` (run time %.0f min).", fmtNum(demand), m3, cfg.peak, cfg.offPeak, secs / 60);
L(end+1) = "";
L(end+1) = "## Summary for executives";
L(end+1) = "";
E = executiveSummary(cfg, lc, rf, st, usable, demand, prev, m3, x, M);
L = [L(:); E(:)];
L(end+1) = "";
L(end+1) = "![Saving by storage size, stored water over the day, energy per m" + char(179) + " by source](whatif_storage_sources.png)";
L(end+1) = "";
% (a)
L(end+1) = "## (a) How much head-tank storage would make time-of-use pumping pay?";
L(end+1) = "";
L(end+1) = "### Method";
L(end+1) = "";
L(end+1) = sprintf("- **Storage sizes.** NPL2_HT and NPL3_HT together hold %s %s between their minimum and maximum levels " + ...
    "today, %.0f minutes of demand. Each size scales both tanks' volume (diameter %s %sk) and keeps their levels, so a " + ...
    "given level gives customers the same pressure as today.", fmtNum(usable), m3, 60 * usable / (demand / 24), x, ...
    char(8730));
L(end+1) = "- **Plans.** For each size: the lowest-energy reference (ignores the tariff; what good operation achieves " + ...
    "without time-of-use scheduling) and the lowest-cost plan under the assumed tariff. Both use a 10% tank reserve and " + ...
    "the customer floors of `pump_plans.md` (10 m, or the model's own minimum where lower: Burapa, IEAT4/5/6).";
L(end+1) = sprintf("- **Optimiser.** As `optimize_pumps.m`: a station-level MILP (`intlinprog`, 0.5%% gap, 300 s limit) picks the " + ...
    "pumps running at each station in each hour; every schedule is run through `validate_plan` (24 h EPANET); up to %d " + ...
    "rounds raise only the planning margins (tank floor, pressure margin, end level, pump-curve margin) when EPANET " + ...
    "misses the fixed spec. A saving counts only when both plans pass.", cfg.maxRounds);
L(end+1) = sprintf("- **What changed, and why.** Bigger tanks swing over a wide band of levels, and level matters in this " + ...
    "network: on the snapshot grid (%.0f-%.0f%% full), %s. So the MILP uses tank inflows, pump power and customer " + ...
    "pressures that depend on both tank levels (fitted on %s EPANET snapshots; still additive station by station; fit " + ...
    "within %s %s/h for tank inflows, %.0f kW for power, %.2f m for pressures). It multiplies the pump choice by " + ...
    "the start-of-hour level exactly, so it steps the tanks the way EPANET does with 1 h steps. Customer floors and " + ...
    "the NPL2 pump-curve limit are constraints in every hour.", 100 * M.bandLo, 100 * M.bandHi, levelEffects(M, m3), ...
    fmtNum(M.nValid), strjoin(compose("%.0f", M.maxErrQ), " / "), m3, M.maxErrP, M.maxErrC);
L(end+1) = "- **Repeatable day.** The optimiser chooses the level the day starts at, and the day must end at least as " + ...
    "full. `optimize_pumps.m` starts at 85% at midnight, which leaves only 22:00-24:00 to refill after the peak and so caps " + ...
    "what any tank size can shift (checked below at the largest size).";
th = M.theta(1, :, 1);
need = compose("%d pumps from %.0f%%", find(th > 0)' - 1, 100 * th(th > 0)');
anyLevel = M.allowed{1}(M.allowed{1} > 0 & th(M.allowed{1} + 1) == 0);
L(end+1) = sprintf("- **Pump-curve limit and solver details.** NPL2 pumps stay on their curve only with NPL2_HT full enough " + ...
    "(%s; %s pumps at any level in the band); counts that need more than the %.0f%% plan ceiling are never used. The " + ...
    "MILP branches on ""at least k pumps"" choices per station and hour (the same bound as one choice per count, but it " + ...
    "solved several times faster); each lowest-cost plan starts from the reference schedule, so it can only improve on " + ...
    "it; plans keep %.1f m above every customer floor to cover the fitted pressure error.", strjoin(need, ", "), ...
    strjoin(string(anyLevel), " or "), 100 * cfg.planMax, cfg.pressureMargin);
L(end+1) = "";
L(end+1) = "### Results";
L(end+1) = "";
L(end+1) = "| storage | usable volume " + m3 + " | hours of demand | reference: EPANET check | reference THB/day | lowest cost: EPANET check | " + ...
    "lowest cost THB/day | **time-of-use saving** | saving THB/day | MILP estimate | lowest cost vs today's reference | " + ...
    "off-peak share of energy (ref / lowest cost) | kWh/" + m3 + " (ref / lowest cost) | tank levels, lowest cost (min-max) |";
L(end+1) = "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|";
for i = 1:height(lc)
    j = find(rf.storage_scale == lc.storage_scale(i));
    L(end+1) = sprintf("| %g%s | %s | %.1f | %s | %s | %s | %s | **%s** | %s | %s | %s | %s | %s | %s |", lc.storage_scale(i), x, ...
        fmtNum(lc.usable_volume_m3(i)), lc.storage_hours(i), checkCell(rf(j, :)), fmtNum(rf.cost_thb(j)), ...
        checkCell(lc(i, :)), fmtNum(lc.cost_thb(i)), pctText(lc.saving_pct(i)), fmtNum(lc.saving_thb_per_day(i)), ...
        pctText(lc.model_saving_pct(i)), pctText(lc.saving_vs_today_pct(i)), ...
        sprintf("%.0f%% / %.0f%%", rf.offpeak_energy_pct(j), lc.offpeak_energy_pct(i)), ...
        sprintf("%.4f / %.4f", rf.kwh_per_m3(j), lc.kwh_per_m3(i)), storedRange(lc(i, :), tankNames)); %#ok<AGROW>
end
L(end+1) = "";
L(end+1) = "Time-of-use saving = 1 - lowest-cost plan / reference at the same storage size, both from EPANET; ""MILP " + ...
    "estimate"" is the optimiser's own figure before the EPANET check; ""vs today's reference"" compares with the " + ...
    "lowest-energy plan for today's tanks, so it adds what steadier pumping with bigger tanks saves. Differences under " + ...
    "about the MILP gap (0.5%, more where a solve stopped at the 300 s limit) are within the optimiser's tolerance. " + ...
    "With today's tanks the solves stop at the 300 s limit with a 2-3% gap; that is a weak bound rather than a poor " + ...
    "plan (in a development test a 20-minute solve improved the 1" + char(215) + " reference by only 0.1%). " + ...
    "Full KPIs: `whatif_storage_kpis.csv`; hourly schedules and EPANET tank levels: `whatif_storage_schedule.csv`.";
for i = 1:height(fx)
    L(end+1) = ""; %#ok<AGROW>
    j = find(lc.storage_scale == fx.storage_scale(i), 1);
    L(end+1) = sprintf("**Start rule check (%g%s storage).** The same lowest-cost plan with `optimize_pumps.m`'s start rule " + ...
        "(tanks 85%% full at midnight, ending at least as full; check: %s) costs %s THB/day, %s than the reference at this " + ...
        "size, against %s with a free start. Holding the tanks that full makes every pump lift against more head, which " + ...
        "costs more than time-of-use pumping saves.", fx.storage_scale(i), x, checkCell(fx(i, :)), fmtNum(fx.cost_thb(i)), ...
        relText(fx.saving_pct(i)), relText(lc.saving_pct(j))); %#ok<AGROW>
end
L(end+1) = "";
for r = runs
    tag = sprintf("%g%s %s", r.scale, x, plans(r.plan).name);
    if isempty(r.best)
        L(end+1) = tag + ": " + strjoin(r.log, "; ") + "."; %#ok<AGROW>
    else
        L(end+1) = sprintf("%s: %d round(s), MILP gap %s - %s.", tag, r.rounds, gapText(r.best.gap), ...
            strjoin(r.log, "; ")); %#ok<AGROW>
    end
end
if prev.found
    i = find(rf.storage_scale == 1, 1);
    if ~isempty(i) && rf.passes(i)
        L(end+1) = "";
        L(end+1) = sprintf("Today's tanks: this reference uses %s kWh/day (%.4f kWh/%s), %s than the reference in " + ...
            "`pump_plans.md` (%s kWh/day, %.4f kWh/%s), which plans on tank inflows measured near full and starts at 85%%. " + ...
            "The difference comes from where the tanks are held (see the summary).", fmtNum(rf.energy_kwh(i)), ...
            rf.kwh_per_m3(i), m3, signedPct(rf.energy_kwh(i) / prev.energy_kwh - 1), fmtNum(prev.energy_kwh), ...
            prev.kwh_per_m3, m3);
    end
end
L(end+1) = "";
% (b)
L(end+1) = "## (b) Cost per " + m3 + " by source and pump combination";
L(end+1) = "";
L(end+1) = "EPANET snapshots of every station combination with both head tanks 85% full (the pump plans' start level). " + ...
    "kWh/" + m3 + " = station pump power / station flow; THB/" + m3 + " = kWh/" + m3 + " " + x + " tariff (energy only, assumed tariff).";
L(end+1) = "";
L(end+1) = "**Pump efficiency used.** The model's [ENERGY] section gives every pump a global 75%; the .inp [CURVES] " + ...
    "section has three efficiency curves. **NPL_2-Eff** matches the NPL2 pumps' head curve NPL_2 and is used for them " + ...
    "(efficiency at each pump's flow). **DK_1-Eff** and **BPK_Eff** belong to the DK_1 and BPK head curves, which no pump " + ...
    "at these stations uses, so they do not apply. NPL3 (head curve NPL3-115) and TM Pond (TM_Pond) have no efficiency " + ...
    "curve: **75%** (model global) for both. Part (a) uses EPANET's 75% for every pump, like `pump_plans.md`.";
L(end+1) = "";
L(end+1) = "| station | source (head) | feeds | pumps | flow " + m3 + "/h | flow per pump CMD | pump head m | efficiency | " + ...
    "kWh/" + m3 + " at 75% | **kWh/" + m3 + "** | THB/" + m3 + " off-peak | THB/" + m3 + " peak | kWh/" + m3 + " at 50% / 90% full |";
L(end+1) = "|---|---|---|---|---|---|---|---|---|---|---|---|---|";
for i = 1:height(st)
    if ~st.valid_85(i), continue; end
    L(end+1) = sprintf("| %s | %s (%.2f m) | %s | %d | %s | %s | %.1f | %.1f%% (%s) | %.4f | **%.4f** | %.3f | %.3f | %s / %s |", ...
        st.station(i), st.source(i), st.source_head_m(i), st.feeds(i), st.pumps(i), fmtNum(st.flow_m3h(i)), ...
        fmtNum(st.flow_per_pump_cmd(i)), st.head_m(i), st.efficiency_pct(i), ...
        ifelse(st.efficiency_source(i) == "model global 75%", "model", st.efficiency_source(i)), ...
        st.kwh_per_m3_model75(i), st.kwh_per_m3_85(i), st.thb_per_m3_offpeak(i), st.thb_per_m3_peak(i), ...
        numText(st.kwh_per_m3_50(i)), numText(st.kwh_per_m3_90(i))); %#ok<AGROW>
end
bad = st(~st.valid_85, :);
items = strings(0, 1);
for nm = unique(bad.station, 'stable')'
    n = bad.pumps(bad.station == nm);
    if isscalar(n)
        items(end+1) = sprintf("%s with %s", nm, pumpsText(n)); %#ok<AGROW>
    else
        items(end+1) = sprintf("%s with %d %s %d pumps", nm, min(n), ifelse(max(n) - min(n) == 1, "or", "to"), max(n)); %#ok<AGROW>
    end
end
L(end+1) = "";
L(end+1) = "Not valid with the tanks 85% full: " + strjoin(items, " and ") + " (EPANET: the pumps run beyond the end " + ...
    "of their curve or cannot deliver the head). With the tanks half full, NPL2 needs " + validAt50(st) + " pumps running.";
L(end+1) = "";
L(end+1) = sprintf("**Combinations** (%d valid with at least one pump; all in `whatif_combination_cost.csv`, with each " + ...
    "station's flow, net tank inflows and the customer pressure margin). Cheapest and dearest per %s:", height(cb), m3);
L(end+1) = "";
L(end+1) = "| NPL2 + NPL3 + TM Pond pumps | flow " + m3 + "/h | kWh/" + m3 + " | THB/" + m3 + " off-peak | THB/" + m3 + " peak | net inflow NPL2_HT / NPL3_HT " + m3 + "/h | can run all day |";
L(end+1) = "|---|---|---|---|---|---|---|";
show = unique([1:min(5, height(cb)), max(1, height(cb) - 2):height(cb)]);
for i = show
    L(end+1) = sprintf("| %d + %d + %d | %s | %.4f | %.3f | %.3f | %+.0f / %+.0f | %s |", cb.npl2_pumps(i), cb.npl3_pumps(i), ...
        cb.tm_pond_pumps(i), fmtNum(cb.total_flow_m3h(i)), cb.kwh_per_m3(i), cb.thb_per_m3_offpeak(i), ...
        cb.thb_per_m3_peak(i), cb.npl2_ht_net_inflow_m3h(i), cb.npl3_ht_net_inflow_m3h(i), ...
        ifelse(cb.can_run_all_day(i), "yes", "no")); %#ok<AGROW>
end
L(end+1) = "";
L(end+1) = sprintf("""Can run all day"": both tanks fill (net inflow %s 0) and every customer is above its floor, so the " + ...
    "combination alone could meet today's %s %s/day.", char(8805), fmtNum(demand), m3);
i = find(cb.can_run_all_day, 1);
if ~isempty(i)
    L(end+1) = sprintf("Cheapest such combination: %d + %d + %d pumps, %.4f kWh/%s (%.3f THB/%s off-peak).", ...
        cb.npl2_pumps(i), cb.npl3_pumps(i), cb.tm_pond_pumps(i), cb.kwh_per_m3(i), m3, cb.thb_per_m3_offpeak(i), m3);
end
L(end+1) = "";
L(end+1) = "## Files";
L(end+1) = "";
L(end+1) = "- `whatif_storage_kpis.csv`: one row per storage size and plan (EPANET KPIs, saving, MILP estimate, tank levels).";
L(end+1) = "- `whatif_storage_schedule.csv`: pumps running per station and hour, tariff, EPANET tank levels at the start of each hour.";
L(end+1) = "- `whatif_station_cost.csv`: per station and pump count, at 50% / 85% / 90% full.";
L(end+1) = "- `whatif_combination_cost.csv`: every valid station combination at 85% full, cheapest first.";
L(end+1) = "- `whatif_storage_sources.png`: the figure above.";
end

function E = executiveSummary(cfg, lc, rf, st, usable, demand, prev, m3, x, M)
% Plain-language conclusions, written from the EPANET-checked results
E = strings(0, 1);
sv = lc.saving_pct;
k = lc.storage_scale;
sizes = strings(0, 1);
for i = 1:height(lc)
    if k(i) == 1, where = "with today's tanks"; else, where = sprintf("at %g%s", k(i), x); end
    if isnan(sv(i)), sizes(end+1) = "no valid plan " + where; %#ok<AGROW>
    else, sizes(end+1) = pctText(sv(i)) + " " + where; %#ok<AGROW>
    end
end
if numel(sizes) > 1, sizes = strjoin(sizes(1:end - 1), ", ") + " and " + sizes(end); end
best = max(sv, [], 'omitnan');
ib = find(sv == best, 1);
meaningful = find(sv >= 3, 1);
if ~isempty(meaningful)
    below = find(k < k(meaningful) & ~(sv >= 3), 1, 'last');
    if isempty(below), need = sprintf("%g%s", k(meaningful), x);
    else, need = sprintf("between %g%s and %g%s", k(below), x, k(meaningful), x); end
    verdict = sprintf("A saving of 3%% or more (the low end of the 3-5%% hoped for) needs %s today's head-tank storage: " + ...
        "%g%s means about %s %s more elevated storage, for about %s THB/year at the assumed tariff, before the cost of " + ...
        "building it.", need, k(meaningful), x, fmtNum(round((k(meaningful) - 1) * usable, -3)), m3, ...
        millions(365 * lc.saving_thb_per_day(meaningful)));
    head = "**Time-of-use pumping pays only with much more head-tank storage.**";
elseif ~isnan(best)
    verdict = sprintf("No size tested reaches the 3-5%% hoped for: the best, %g%s (about %s %s more elevated storage), " + ...
        "saves %s, about %s THB/year at the assumed tariff, before the cost of building it.", k(ib), x, ...
        fmtNum(round((k(ib) - 1) * usable, -3)), m3, pctText(best), millions(365 * lc.saving_thb_per_day(ib)));
    head = "**Bigger head tanks would not make time-of-use pumping pay.**";
else
    verdict = "No size gave a lowest-cost plan that passes the EPANET check.";
    head = "**No valid time-of-use plan.**";
end
E(end+1) = sprintf("- %s Shifting pumping out of the 09:00-22:00 peak saves %s, as a share of the daily pumping cost " + ...
    "(EPANET-checked, against the lowest-energy plan at the same size; differences under about 0.5%% are within the " + ...
    "optimiser's tolerance; today's tanks hold %s %s, %.0f minutes of demand). %s", head, sizes, fmtNum(usable), m3, ...
    60 * usable / (demand / 24), verdict);
% Why: marginal energy of the last pumps, and the pressure floor
[mLast, nmLast] = deal(nan(1, 3), strings(1, 3));
names = unique(st.station, 'stable');
for i = 1:numel(names)
    t = st(st.station == names(i) & st.valid_85, :);
    if height(t) < 2, continue; end
    mLast(i) = (t.power_kw(end) - t.power_kw(end - 1)) / (t.flow_m3h(end) - t.flow_m3h(end - 1));
    nmLast(i) = sprintf("%s %.2f", names(i), mLast(i));
end
n3 = st(st.station == "NPL3" & st.valid_85, :);
i1 = find(rf.storage_scale == 1, 1);
iAvg = i1;
if isempty(iAvg), [~, iAvg] = min(rf.storage_scale); end
avg = rf.kwh_per_m3(iAvg);
E(end+1) = sprintf("- **Why: the pumps, not the tanks, limit the shift.** Moving pumping into the 11 off-peak hours means running " + ...
    "more pumps at once, and more flow through the same discharge mains raises the head every pump works against (NPL3: " + ...
    "%.0f m with one pump, %.0f m with six). The last pump at each station adds water at %s kWh/%s, against %.3f on " + ...
    "average in the lowest-energy plan, which uses up most of the %.0f%% off-peak discount. Customer pressure also limits " + ...
    "the drawdown: NPL3_HT must stay above about %.0f%% full to keep every customer above its floor (%.0f%% with no TM Pond " + ...
    "pump running).", n3.head_m(1), n3.head_m(end), strjoin(nmLast(nmLast ~= ""), ", "), m3, avg, ...
    100 * (1 - cfg.offPeak / cfg.peak), 100 * M.pressureLow(2), 100 * M.pressureLowNoTM(2));
% What storage does buy: steadier pumping
i10 = find(lc.storage_scale == max(lc.storage_scale), 1);
r10 = find(rf.storage_scale == max(rf.storage_scale), 1);
if ~isempty(i10) && ~isnan(lc.saving_vs_today_pct(i10)) && max(lc.storage_scale) > 1
    E(end+1) = sprintf("- **What extra storage does buy is steadier pumping.** Against the lowest-energy plan with today's tanks, " + ...
        "the %g%s lowest-cost plan costs %s less per day (about %s THB/year); only %.1f points of that come from " + ...
        "time-of-use. The rest is steadier pumping: bigger tanks let the stations run one efficient pump mix all day " + ...
        "(%.4f kWh/%s at %g%s against %.4f today).", lc.storage_scale(i10), x, pctText(lc.saving_vs_today_pct(i10)), ...
        millions(365 * (rf.cost_thb(iAvg) - lc.cost_thb(i10))), sv(i10), rf.kwh_per_m3(r10), m3, rf.storage_scale(r10), ...
        x, avg);
end
% Where savings are instead
if prev.found && ~isempty(i1) && rf.passes(i1)
    E(end+1) = sprintf("- **Where the savings are instead:** pump into lower tanks. The lowest-energy plan for today's tanks keeps " + ...
        "them only as full as the customer floors need (NPL2_HT %.0f-%.0f%%, NPL3_HT %.0f-%.0f%%) and uses %.4f kWh/%s, %s " + ...
        "than the reference in `pump_plans.md` (%.4f, which starts and ends the day with both tanks 85%% full). That " + ...
        "needs no new assets but " + ...
        "leaves less water in reserve, so it is an operating decision for Eastwater. Beyond that: favour the cheaper " + ...
        "sources (next point), and cut the head the pumps work against at high flow or fit more efficient pumps, which " + ...
        "needs pump tests and SCADA data.", rf.npl2ht_min_pct(i1), rf.npl2ht_max_pct(i1), rf.npl3ht_min_pct(i1), ...
        rf.npl3ht_max_pct(i1), avg, m3, signedPct(avg / prev.kwh_per_m3 - 1), prev.kwh_per_m3);
end
% Cheapest source
v = st(st.valid_85, :);
[~, a] = min(v.kwh_per_m3_85);
[~, z] = max(v.kwh_per_m3_85);
[hLow, iLow] = min(v.source_head_m);
lift = "";
if v.station(iLow) == v.station(z)
    lift = sprintf(" %s draws from %s at %.2f m, %.0f m below the other stations' reservoirs, so it lifts further.", ...
        v.station(z), v.source(iLow), hLow, max(v.source_head_m) - hLow);
end
E(end+1) = sprintf("- **Cheapest water per %s: %s with %s** at %.3f kWh/%s (%.2f THB/%s off-peak, %.2f at peak); " + ...
    "**dearest: %s with %s** at %.3f kWh/%s (%.2f / %.2f THB/%s). %s%s", m3, v.station(a), pumpsText(v.pumps(a)), ...
    v.kwh_per_m3_85(a), m3, v.thb_per_m3_offpeak(a), m3, v.thb_per_m3_peak(a), v.station(z), pumpsText(v.pumps(z)), ...
    v.kwh_per_m3_85(z), m3, v.thb_per_m3_offpeak(z), v.thb_per_m3_peak(z), m3, sourceSentence(v, m3), lift);
E(end+1) = "- **What would change these conclusions:** Eastwater's real tariff (a wider peak/off-peak gap or demand " + ...
    "charges make shifting worth more), hourly demand from SCADA (the model's is flat), efficiency curves for the NPL3 " + ...
    "and TM Pond pumps (75% assumed here), and Eastwater's minimum tank levels (the lower-tank saving depends on them). " + ...
    "The cost of building extra storage is not included.";
end

function s = sourceSentence(v, m3)
% How each station's cost per m3 moves with the number of pumps running, and which is cheapest at full output
items = strings(0, 1);
names = unique(v.station, 'stable');
full = nan(size(names));
for i = 1:numel(names)
    t = v(v.station == names(i), :);
    full(i) = t.kwh_per_m3_85(end);
    items(end+1) = sprintf("%s %.3f-%.3f (%d-%d pumps)", names(i), min(t.kwh_per_m3_85), max(t.kwh_per_m3_85), ...
        min(t.pumps), max(t.pumps)); %#ok<AGROW>
end
[~, a] = min(full);
[~, z] = max(full);
s = sprintf("kWh/%s rises with the number of pumps running, because more flow through the same discharge main needs " + ...
    "more head: %s. At full output %s is the cheapest source and %s the dearest.", m3, strjoin(items, "; "), ...
    names(a), names(z));
end

function s = levelEffects(M, m3)
% One sentence on how much level matters, from the grid snapshots
s = sprintf("with %d + %d + %d pumps running, the net inflows to NPL2_HT / NPL3_HT go from %s %s/h with both tanks " + ...
    "%.0f%% full to %s %s/h at %.0f%% full, and the lowest customer pressure from %.1f to %.1f m", M.stats.combo, ...
    strjoin(signedNum(M.stats.Qlo), " / "), m3, 100 * M.bandLo, strjoin(signedNum(M.stats.Qhi), " / "), m3, ...
    100 * M.bandHi, M.stats.Plo, M.stats.Phi);
end

function s = validAt50(st)
t = st(st.station == "NPL2" & st.valid_50, :);
if isempty(t), s = "all six"; else, s = sprintf("at least %d", min(t.pumps)); end
end

function s = storedRange(row, tankNames)
t1 = lower(erase(tankNames(1), "_"));
t2 = lower(erase(tankNames(2), "_"));
if isnan(row.(t1 + "_min_pct")), s = "-"; return; end
s = sprintf("%s %.0f-%.0f%%, %s %.0f-%.0f%%", tankNames(1), row.(t1 + "_min_pct"), row.(t1 + "_max_pct"), ...
    tankNames(2), row.(t2 + "_min_pct"), row.(t2 + "_max_pct"));
end

function s = checkCell(row)
% Our spec (passes / fails), with EPANET's own grade when it is not a clean Pass
if row.status == "no schedule", s = "no schedule"; return; end
if row.passes, s = "passes"; else, s = "fails"; end
if row.status ~= "Pass", s = s + " (EPANET " + lower(row.status) + ")"; end
end

function s = pumpsText(n)
if n == 1, s = "1 pump"; else, s = sprintf("%d pumps", n); end
end

function s = millions(v)
if isnan(v), s = "-"; else, s = sprintf("%.1f million", v / 1e6); end
end

function s = signedNum(x)
s = strings(size(x));
for i = 1:numel(x)
    if x(i) >= 0, s(i) = "+" + fmtNum(x(i)); else, s(i) = char(8722) + fmtNum(-x(i)); end
end
end

function s = relText(savingPct)
% A saving as "x% cheaper" or "x% dearer"
if isnan(savingPct), s = "n/a";
elseif savingPct >= 0, s = sprintf("%.1f%% cheaper", savingPct);
else, s = sprintf("%.1f%% dearer", -savingPct);
end
end

function s = pctText(v)
if isnan(v), s = "n/a"; else, s = sprintf("%.1f%%", v); end
end

function s = signedPct(v)
if v < 0, s = sprintf("%.1f%% less", -100 * v); else, s = sprintf("%.1f%% more", 100 * v); end
end

function s = numText(v)
if isnan(v), s = "-"; else, s = sprintf("%.4f", v); end
end

function txt = gapText(gap)
if isempty(gap) || ~isfinite(gap), txt = "n/a"; else, txt = sprintf("%.2f%%", 100 * gap); end
end

function v = ifelse(cond, a, b)
if cond, v = a; else, v = b; end
end

function s = fmtNum(x)
s = strings(size(x));
for i = 1:numel(x)
    if isnan(x(i)), s(i) = "-"; continue; end
    s(i) = string(regexprep(sprintf('%.0f', x(i)), '(\d)(?=(\d{3})+$)', '$1,'));
end
end
