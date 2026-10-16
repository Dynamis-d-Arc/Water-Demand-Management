function R = validate_plan(d, plan, opts)
%VALIDATE_PLAN  Run a supply plan through EPANET and grade it Pass / Warning / Fail.
%   R = validate_plan(d, plan, opts) runs an extended-period simulation of the network loaded
%   in the EPANET-MATLAB Toolkit object d with the plan applied, and checks the result against
%   the hydraulic constraints. d is modified (patterns, times, initial pump status), so reload
%   the model when a plan must not inherit another plan's settings.
%
%   plan fields (all optional):
%     hours        simulation length in hours (default 24)
%     demandMult   hours x 1 multiplier on every customer demand (default 1)
%     pumpOn       hours x nPumps 0/1 schedule, columns in d.getLinkPumpIndex order
%                  (default: pumps keep the model's status)
%     tariff       hours x 1 electricity price, THB/kWh (default 0)
%   opts fields (all optional):
%     minPressure     hard floor at customer nodes, m; below it = Fail (default 0)
%     targetPressure  service target at customer nodes, m; scalar or one per customer in
%                     customer order; below it = Warning (default 10)
%     endTankTol      allowed drop in tank level from start to end, m (default 0.5)
%
%   R.status is "Pass", "Warning" or "Fail"; R.reasons says why. R.kpi has energy (kWh),
%   cost (THB), delivered volume (m3), kWh/m3, THB/m3 and the lowest customer pressure.
%   R.customers, R.tanks and R.steps hold the detail; R.tankLevels is steps x tanks (m above
%   the tank floor) and R.pumpFlow the flow of every pump at every step.

if nargin < 2, plan = struct(); end
if nargin < 3, opts = struct(); end
hours = getf(plan, 'hours', 24);
mult = getf(plan, 'demandMult', ones(hours, 1));
pumpOn = getf(plan, 'pumpOn', []);
tariff = getf(plan, 'tariff', zeros(hours, 1));
minP = getf(opts, 'minPressure', 0);
targetP = getf(opts, 'targetPressure', 10);
endTol = getf(opts, 'endTankTol', 0.5);

d.setTimeSimulationDuration(hours * 3600);
d.setTimeHydraulicStep(3600);
d.setTimePatternStep(3600);
d.setTimeReportingStep(3600);

ids = d.getNodeNameID;
linkIds = d.getLinkNameID;
junc = d.getNodeJunctionIndex;
base = d.getNodeBaseDemands;
base = base{1};
cust = junc(base(junc) > 0);
tanks = d.getNodeTankIndex;
pumps = d.getLinkPumpIndex;
elev = d.getNodeElevations;
tankMin = d.getNodeTankMinimumWaterLevel;
tankMax = d.getNodeTankMaximumWaterLevel;

d.setNodeDemandPatternIndex(cust, repmat(setPatternById(d, 'PLAN_DEMAND', mult), 1, numel(cust)));
if ~isempty(pumpOn)
    for k = 1:numel(pumps)
        d.setLinkPumpPatternIndex(pumps(k), setPatternById(d, sprintf('PLAN_PUMP_%d', k), pumpOn(:, k)));
        d.setLinkInitialStatus(pumps(k), pumpOn(1, k));
    end
end

% Step-by-step run so warnings and intermediate events are captured
steps = struct('t', {}, 'dt', {}, 'code', {}, 'demand', {}, 'power', {}, 'custP', {}, ...
               'juncMinP', {}, 'negJunc', {}, 'tankLevel', {}, 'pumpFlow', {});
d.openHydraulicAnalysis;
d.initializeHydraulicAnalysis(0);
tstep = 1;
while tstep > 0
    t = d.runHydraulicAnalysis;
    code = d.Errcode;
    p = d.getNodePressure;
    head = d.getNodeHydraulicHead;
    dem = d.getNodeActualDemand;
    s = struct('t', double(t), 'dt', 0, 'code', double(code), 'demand', sum(dem(cust)), ...
               'power', d.getLinkEnergy(pumps), 'custP', p(cust), 'juncMinP', min(p(junc)), ...
               'negJunc', sum(p(junc) < 0), 'tankLevel', head(tanks) - elev(tanks), ...
               'pumpFlow', d.getLinkFlows(pumps));
    tstep = d.nextHydraulicAnalysisStep;
    s.dt = double(tstep);
    steps(end+1) = s; %#ok<AGROW>
end
d.closeHydraulicAnalysis;

% KPIs: integrate over the variable-length hydraulic steps
tH = [steps.t]' / 3600;
dtH = [steps.dt]' / 3600;
power = vertcat(steps.power);
hourIdx = min(floor(tH) + 1, numel(tariff));
energy = sum(sum(power, 2) .* dtH);
cost = sum(sum(power, 2) .* dtH .* tariff(hourIdx));
delivered = sum([steps.demand]' .* dtH / 24);
custP = vertcat(steps.custP);
level = vertcat(steps.tankLevel);
codes = [steps.code]';
R.kpi = struct('energy_kwh', energy, 'cost_thb', cost, 'delivered_m3', delivered, ...
               'kwh_per_m3', energy / delivered, 'thb_per_m3', cost / delivered, ...
               'min_customer_pressure_m', min(custP(:)));

% Checks
reasons = strings(0, 1);
notes = strings(0, 1);
fail = false;
warn = false;
% Code 4 is what EPANET reports when a pump is forced off, e.g. pumping against a full tank:
% wasteful but not a service failure, which the pressure and tank checks below catch.
fatal = codes(codes == 1 | codes == 3 | codes > 100);
if ~isempty(fatal)
    fail = true;
    reasons(end+1) = "EPANET: " + strjoin(codeText(fatal), "; ");
end
soft = codes(codes == 2 | codes == 4 | codes == 5);
if ~isempty(soft)
    warn = true;
    reasons(end+1) = "EPANET: " + strjoin(codeText(soft), "; ");
end
nodeMin = min(custP, [], 1)';
target = targetP(:) .* ones(numel(cust), 1);
bad = nodeMin < minP;
low = ~bad & nodeMin < target - 1e-6;
if any(bad)
    fail = true;
    reasons(end+1) = sprintf("pressure below %g m at %s", minP, strjoin(string(ids(cust(bad))), ", "));
end
if any(low)
    warn = true;
    reasons(end+1) = sprintf("pressure below target at %s", strjoin(string(ids(cust(low))), ", "));
end
for k = 1:numel(tanks)
    name = string(ids{tanks(k)});
    if any(level(:, k) <= tankMin(k) + 0.01)
        fail = true;
        reasons(end+1) = sprintf("tank %s runs empty at %g h", name, tH(find(level(:, k) <= tankMin(k) + 0.01, 1)));
    elseif level(end, k) < level(1, k) - endTol
        warn = true;
        reasons(end+1) = sprintf("tank %s ends %.1f m below its start level (plan cannot repeat daily)", ...
                                 name, level(1, k) - level(end, k));
    end
    if any(level(:, k) >= tankMax(k) - 0.01)
        notes(end+1) = sprintf("tank %s reaches its maximum level", name); %#ok<AGROW>
    end
end
negJ = max([steps.negJunc]);
if negJ > 0
    notes(end+1) = sprintf("%d junction(s) without demand go below 0 m (pump suction pipework)", negJ);
end
if fail, R.status = "Fail"; elseif warn, R.status = "Warning"; else, R.status = "Pass"; end
R.reasons = reasons;
R.notes = notes;

R.customers = table(string(ids(cust))', base(cust)', nodeMin, target, ...
    'VariableNames', {'node', 'base_demand_cmd', 'min_pressure_m', 'target_m'});
R.tanks = table(string(ids(tanks))', level(1, :)', min(level, [], 1)', max(level, [], 1)', level(end, :)', ...
    tankMin(:), tankMax(:), 'VariableNames', {'tank', 'start_m', 'min_m', 'max_m', 'end_m', 'limit_min_m', 'limit_max_m'});
R.steps = table(tH, dtH, codes, [steps.demand]', sum(power, 2), [steps.juncMinP]', ...
    'VariableNames', {'time_h', 'duration_h', 'epanet_code', 'demand_cmd', 'pump_power_kw', 'min_junction_pressure_m'});
R.tankLevels = level;
R.pumpFlow = array2table(vertcat(steps.pumpFlow), 'VariableNames', string(linkIds(pumps)));
end

function idx = setPatternById(d, id, values)
names = d.getPatternNameID;
if ~isempty(names) && any(strcmp(names, id))
    idx = d.getPatternIndex(id);
    d.setPattern(idx, values(:)');
else
    idx = d.addPattern(id, values(:)');
end
end

function v = getf(s, name, default)
if isfield(s, name) && ~isempty(s.(name)), v = s.(name); else, v = default; end
end

function txt = codeText(codes)
txt = strings(0, 1);
for c = unique(codes)'
    txt(end+1) = warningText(c); %#ok<AGROW>
end
end

function txt = warningText(code)
switch code
    case 1, txt = "system hydraulically unbalanced";
    case 2, txt = "system may be hydraulically unstable";
    case 3, txt = "system disconnected";
    case 4, txt = "pumps forced off: cannot deliver the head (e.g. against a full tank)";
    case 5, txt = "valves cannot deliver enough flow";
    otherwise, txt = sprintf("error %d", code);
end
end
