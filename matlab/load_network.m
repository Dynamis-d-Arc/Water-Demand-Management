function [d, cleanup] = load_network(inpFile, backend)
%LOAD_NETWORK  Load an EPANET model from a temporary copy.
%   [d, cleanup] = load_network(inpFile) keeps EPANET's report/output files out of the
%   model's own folder. Keep `cleanup` in scope; clearing it unloads EPANET and deletes the
%   copy. Both backends offer the same methods for this project's scripts.
%
%   backend "epyt" (default): EPANET through the Python epyt package (EpytNetwork). Works
%       under Windows Smart App Control, which blocks the adapter DLL the toolkit compiles.
%   backend "toolkit": the EPANET-MATLAB Toolkit (needs the MinGW compiler, and a PC where
%       Smart App Control does not block %TEMP%\epanet2_thunk_pcwin64.dll).

if nargin < 2, backend = "epyt"; end
work = tempname;
mkdir(work);
copyfile(inpFile, fullfile(work, 'model.inp'));
if backend == "epyt"
    d = EpytNetwork(fullfile(work, 'model.inp'));
else
    here = cd(work);                    % the toolkit finds the file with which()
    restore = onCleanup(@() cd(here));
    d = epanet('model.inp');
end
cleanup = onCleanup(@() unloadAndRemove(d, work));
end

function unloadAndRemove(d, work)
try
    d.unload;
catch
end
try
    rmdir(work, 's');
catch
end
end
