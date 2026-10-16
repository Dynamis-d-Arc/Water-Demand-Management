classdef EpytNetwork < handle
%EPYTNETWORK  EPANET through the Python epyt package, with the EPANET-MATLAB Toolkit methods
%   this project uses (same names, same 1-based EPANET indices, MATLAB doubles out).
%
%   Why: Windows Smart App Control blocks the adapter DLL that the toolkit's loadlibrary
%   compiles at run time (epanet2_thunk_pcwin64.dll in %TEMP%). epyt ships a prebuilt EPANET
%   DLL that loads under the policy, and gives identical results. Needs MATLAB's Python
%   interface (pyenv) pointing at a Python with epyt installed.
%
%   d = EpytNetwork('model.inp'); ... d.unload;   % usually via load_network

    properties (SetAccess = private)
        py              % the epyt.epanet object
        Errcode = 0     % EPANET code from the last hydraulic step (0 = OK, 1-6 = warning)
    end

    methods
        function obj = EpytNetwork(inpFile)
            py.warnings.filterwarnings('ignore');      % epyt reports EPANET warnings via Python warnings
            obj.py = py.epyt.epanet(char(inpFile), pyargs('display_msg', false, 'display_warnings', false));
        end

        function unload(obj)
            obj.py.unload();
        end

        % ---- counts and indices
        function v = getNodeCount(obj), v = double(obj.py.getNodeCount()); end
        function v = getNodeJunctionCount(obj), v = double(obj.py.getNodeJunctionCount()); end
        function v = getNodeReservoirCount(obj), v = double(obj.py.getNodeReservoirCount()); end
        function v = getNodeTankCount(obj), v = double(obj.py.getNodeTankCount()); end
        function v = getLinkCount(obj), v = double(obj.py.getLinkCount()); end
        function v = getLinkPipeCount(obj), v = double(obj.py.getLinkPipeCount()); end
        function v = getLinkPumpCount(obj), v = double(obj.py.getLinkPumpCount()); end
        function v = getLinkValveCount(obj), v = double(obj.py.getLinkValveCount()); end
        function v = getNodeJunctionIndex(obj), v = toDouble(obj.py.getNodeJunctionIndex()); end
        function v = getNodeTankIndex(obj), v = toDouble(obj.py.getNodeTankIndex()); end
        function v = getLinkPumpIndex(obj), v = toDouble(obj.py.getLinkPumpIndex()); end
        function v = getNodeIndex(obj, id), v = double(obj.py.getNodeIndex(char(id))); end

        function v = getNodeNameID(obj, idx)
            if nargin < 2, v = toCellstr(obj.py.getNodeNameID()); else, v = toCellstr(obj.py.getNodeNameID(pyInts(idx))); end
        end
        function v = getLinkNameID(obj, idx)
            if nargin < 2, v = toCellstr(obj.py.getLinkNameID()); else, v = toCellstr(obj.py.getLinkNameID(pyInts(idx))); end
        end

        % ---- static properties
        function v = getNodeElevations(obj), v = toDouble(obj.py.getNodeElevations()); end
        function v = getNodeBaseDemands(obj)
            % {category 1 base demand for every node}, like the toolkit
            v = {toDouble(obj.py.getNodeBaseDemands().get(py.int(1)))};
        end
        function v = getNodeTankDiameter(obj), v = toDouble(obj.py.getNodeTankDiameter()); end
        function v = getNodeTankInitialLevel(obj), v = toDouble(obj.py.getNodeTankInitialLevel()); end
        function v = getNodeTankMinimumWaterLevel(obj), v = toDouble(obj.py.getNodeTankMinimumWaterLevel()); end
        function v = getNodeTankMaximumWaterLevel(obj), v = toDouble(obj.py.getNodeTankMaximumWaterLevel()); end
        function v = getLinkInitialStatus(obj, idx), v = toDouble(obj.py.getLinkInitialStatus(pyInts(idx))); end
        function v = getPatternNameID(obj), v = toCellstr(obj.py.getPatternNameID()); end
        function v = getPatternIndex(obj, id), v = double(obj.py.getPatternIndex(char(id))); end

        % ---- setters (index list + one value per index, or a scalar for all of them)
        function setNodeBaseDemands(obj, idx, value)
            obj.py.setNodeBaseDemands(pyInts(idx), pyFloats(expand(value, numel(idx))));
        end
        function setNodeTankInitialLevel(obj, value)
            obj.py.setNodeTankInitialLevel(pyFloats(value));
        end
        function setLinkInitialStatus(obj, idx, value)
            obj.py.setLinkInitialStatus(pyInts(idx), pyFloats(expand(value, numel(idx))));
        end
        function setLinkPumpPatternIndex(obj, idx, pattern)
            pattern = expand(pattern, numel(idx));
            for k = 1:numel(idx)                       % scalar calls: epyt's list path expects lists both sides
                obj.py.setLinkPumpPatternIndex(py.int(idx(k)), py.int(pattern(k)));
            end
        end
        function setNodeDemandPatternIndex(obj, idx, pattern)
            obj.py.setNodeDemandPatternIndex(pyInts(idx), pyInts(expand(pattern, numel(idx))));
        end
        function idx = addPattern(obj, id, values)
            idx = double(obj.py.addPattern(char(id), pyFloats(values)));
        end
        function setPattern(obj, idx, values)
            obj.py.setPattern(py.int(idx), pyFloats(values));
        end
        function setTimeSimulationDuration(obj, s), obj.py.setTimeSimulationDuration(py.int(s)); end
        function setTimeHydraulicStep(obj, s), obj.py.setTimeHydraulicStep(py.int(s)); end
        function setTimePatternStep(obj, s), obj.py.setTimePatternStep(py.int(s)); end
        function setTimeReportingStep(obj, s), obj.py.setTimeReportingStep(py.int(s)); end

        % ---- step-by-step hydraulics
        function openHydraulicAnalysis(obj), obj.py.openHydraulicAnalysis(); end
        function initializeHydraulicAnalysis(obj, flag)
            if nargin < 2, flag = 0; end
            obj.py.initializeHydraulicAnalysis(py.int(flag));
        end
        function t = runHydraulicAnalysis(obj)
            t = double(obj.py.runHydraulicAnalysis());
            obj.Errcode = double(obj.py.api.errcode);
        end
        function tstep = nextHydraulicAnalysisStep(obj), tstep = double(obj.py.nextHydraulicAnalysisStep()); end
        function closeHydraulicAnalysis(obj), obj.py.closeHydraulicAnalysis(); end
        function v = getNodePressure(obj), v = toDouble(obj.py.getNodePressure()); end
        function v = getNodeHydraulicHead(obj), v = toDouble(obj.py.getNodeHydraulicHead()); end
        function v = getNodeActualDemand(obj), v = toDouble(obj.py.getNodeActualDemand()); end
        function v = getLinkFlows(obj, idx)
            if nargin < 2, v = toDouble(obj.py.getLinkFlows()); else, v = toDouble(obj.py.getLinkFlows(pyInts(idx))); end
        end
        function v = getLinkEnergy(obj, idx)
            if nargin < 2, v = toDouble(obj.py.getLinkEnergy()); else, v = toDouble(obj.py.getLinkEnergy(pyInts(idx))); end
        end

        % ---- whole-run hydraulics
        function H = getComputedHydraulicTimeSeries(obj)
            % Time (s), Pressure, Head, Demand (steps x nodes), Flow, Energy (steps x links)
            r = obj.py.getComputedHydraulicTimeSeries();
            H = struct('Time', toDouble(r.Time)', 'Pressure', toDouble(r.Pressure), 'Head', toDouble(r.Head), ...
                       'Demand', toDouble(r.Demand), 'Flow', toDouble(r.Flow), 'Energy', toDouble(r.Energy));
        end
    end
end

function v = toDouble(x)
% numpy array / Python list / Python scalar -> MATLAB double (vectors as rows)
if isa(x, 'py.list') || isa(x, 'py.tuple')
    v = cellfun(@double, cell(x));
else
    v = double(x);
end
if isvector(v), v = reshape(v, 1, []); end
end

function c = toCellstr(x)
if isa(x, 'py.str'), c = {char(x)}; return; end
c = cellfun(@char, cell(x), 'UniformOutput', false);
end

function l = pyInts(x)
l = py.list(num2cell(int64(x(:)')));
end

function l = pyFloats(x)
l = py.list(num2cell(double(x(:)')));
end

function v = expand(v, n)
if isscalar(v), v = repmat(v, 1, n); end
end
