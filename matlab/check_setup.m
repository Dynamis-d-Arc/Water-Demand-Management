% check_setup.m  Check MATLAB, the toolboxes the POC flow needs, and that the cleaned data loads.
% Run from water_poc:   matlab -batch "run('matlab/check_setup.m')"
% Licence queries come last: with online licensing they need a signed-in MATLAB and can block.

root = fileparts(fileparts(mfilename('fullpath')));
fprintf('MATLAB %s on %s\n\n', version, computer);

% 1. Cleaned data, both formats (core MATLAB only)
csvFile = fullfile(root, 'data', 'clean', 'bangphra_daily.csv');
matFile = fullfile(root, 'data', 'clean', 'bangphra_daily.mat');
T = readtimetable(csvFile);
fprintf('CSV: %d days x %d columns, %s to %s\n', height(T), width(T), ...
    string(T.Properties.RowTimes(1)), string(T.Properties.RowTimes(end)));
S = load(matFile);
t = datetime(S.bangphra.datenum, 'ConvertFrom', 'datenum');
fprintf('MAT: %d days x %d fields, %s to %s, date_iso is %s\n', numel(t), numel(fieldnames(S.bangphra)), ...
    string(t(1)), string(t(end)), class(S.bangphra.date_iso));
fprintf('Dates match: %d\n', isequal(T.Properties.RowTimes, t(:)));
gap = max(abs(T.use_pwa_chonburi_m3 - S.bangphra.use_pwa_chonburi_m3(:)), [], 'omitnan');
fprintf('PWA values match (max |CSV - MAT|): %g\n', gap);
in2024 = year(T.Properties.RowTimes) == 2024;
fprintf('PWA Chonburi 2024 mean: %.0f m3/day, missing days: %d\n\n', ...
    mean(T.use_pwa_chonburi_m3(in2024), 'omitnan'), sum(isnan(T.use_pwa_chonburi_m3(in2024))));

% 2. Installed products
% product name (as in ver), licence feature name, what the flow uses it for
need = {
    'Statistics and Machine Learning Toolbox', 'Statistics_Toolbox',     'forecast models (fitrensemble, fitrgp)'
    'Econometrics Toolbox',                    'Econometrics_Toolbox',   'ARIMA / regARIMA baselines'
    'Optimization Toolbox',                    'Optimization_Toolbox',   'pump schedule MILP (intlinprog)'
    'Global Optimization Toolbox',             'GADS_Toolbox',           'Plan A/B/C trade-off (gamultiobj)'
    'Deep Learning Toolbox',                   'Neural_Network_Toolbox', 'LSTM (optional)'
    'MATLAB Compiler',                         'Compiler',               'deploying the tool (optional)'
    };
v = ver;
installed = {v.Name};
fprintf('All installed products:\n');
fprintf('  %s %s\n', [string({v.Name}); string({v.Version})]);
fprintf('\n%-42s %-9s %s\n', 'Toolbox needed', 'installed', 'used for');
for k = 1:size(need, 1)
    fprintf('%-42s %-9d %s\n', need{k, 1}, any(strcmp(installed, need{k, 1})), need{k, 3});
end

fprintf('\nEPANET-MATLAB Toolkit on path: %d\n', exist('epanet', 'class') == 8 || exist('epanet', 'file') == 2);
try
    pe = pyenv;
    fprintf('Python for MATLAB: %s (%s)\n', pe.Version, pe.Executable);
catch err
    fprintf('Python for MATLAB: not available (%s)\n', err.message);
end

% 3. Licences (may block until MATLAB has been signed in interactively once)
fprintf('\nLicence checks:\n');
for k = 1:size(need, 1)
    if any(strcmp(installed, need{k, 1}))
        fprintf('  %-42s ... ', need{k, 1});
        fprintf('%d\n', license('test', need{k, 2}));
    end
end
if any(strcmp(installed, 'Statistics and Machine Learning Toolbox'))
    try
        x = T.storage_mcm(end-999:end);
        mdl = fitrensemble((1:1000)', x, 'Method', 'LSBoost', 'NumLearningCycles', 20);
        fprintf('fitrensemble smoke test: OK (%d learners)\n', mdl.NumTrained);
    catch err
        fprintf('fitrensemble smoke test FAILED: %s\n', err.message);
    end
end
