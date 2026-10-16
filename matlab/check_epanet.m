% check_epanet.m  Run the EPANET model from MATLAB and compare with the Python check.
% Run from water_poc:   matlab -batch "run('matlab/check_epanet.m')"
% Uses the epyt backend by default (works under Windows Smart App Control); to use the
% EPANET-MATLAB Toolkit instead:   matlab -batch "backend='toolkit'; run('matlab/check_epanet.m')"

if ~exist('backend', 'var'), backend = "epyt"; end
root = fileparts(fileparts(mfilename('fullpath')));
addpath(fileparts(mfilename('fullpath')));
src = fullfile(fileparts(root), 'Demand-2023 v20RY to MTP new TM2P.inp');
[d, cleanup] = load_network(src, backend);
fprintf('Backend: %s\n', backend);
fprintf('Nodes %d (junctions %d, reservoirs %d, tanks %d), links %d (pipes %d, pumps %d, valves %d)\n', ...
    d.getNodeCount, d.getNodeJunctionCount, d.getNodeReservoirCount, d.getNodeTankCount, ...
    d.getLinkCount, d.getLinkPipeCount, d.getLinkPumpCount, d.getLinkValveCount);

H = d.getComputedHydraulicTimeSeries;
fprintf('Steps: %d, last time %g h\n', numel(H.Time), H.Time(end) / 3600);

ids = d.getNodeNameID;
junc = d.getNodeJunctionIndex;
base = d.getNodeBaseDemands;
base = base{1};
demandNodes = junc(base(junc) > 0);
fprintf('Demand nodes: %d, total base demand %.0f CMD\n', numel(demandNodes), sum(base(demandNodes)));
fprintf('Junctions ever below 0 m: %d\n', sum(min(H.Pressure(:, junc), [], 1) < 0));

% Same nodes as reports/epanet_check.md (Python/epyt) for a side-by-side check
pyRef = readtable(fullfile(root, 'reports', 'epanet_demand_nodes.csv'), 'TextType', 'string');
fprintf('\n%-14s %10s %10s %8s\n', 'node', 'MATLAB min', 'Python min', 'diff');
worst = 0;
for k = 1:height(pyRef)
    i = d.getNodeIndex(char(pyRef.node(k)));
    pm = min(H.Pressure(:, i));
    worst = max(worst, abs(pm - pyRef.min_pressure_m(k)));
    if k <= 6 || pyRef.min_pressure_m(k) < 10
        fprintf('%-14s %10.2f %10.2f %8.3f\n', pyRef.node(k), pm, pyRef.min_pressure_m(k), pm - pyRef.min_pressure_m(k));
    end
end
fprintf('Largest |MATLAB - Python| min-pressure difference over %d nodes: %.3f m\n', height(pyRef), worst);

tanks = d.getNodeTankIndex;
elev = d.getNodeElevations;
for i = tanks
    lvl = H.Head(:, i) - elev(i);
    fprintf('Tank %-8s level start %.2f m, end %.2f m\n', ids{i}, lvl(1), lvl(end));
end
clear cleanup
