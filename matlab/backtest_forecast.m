% backtest_forecast.m  MATLAB port of src/backtest.py: rolling-origin backtest of the baseline
% forecasts and fitrensemble (LSBoost) models on the cleaned Bang Phra data, compared with Python.
% Run from water_poc:   matlab -batch "run('matlab/backtest_forecast.m')"
%
% Same products, baselines, features, test periods and retraining schedule as the Python
% version. One deliberate difference: fitrensemble has no quantile loss, so P10/P90 come from
% the residual quantiles of earlier out-of-sample blocks (rolling conformal intervals). An
% extra warm-up block before the test period seeds those residuals and is not scored.
%
% Writes reports/matlab/backtest_metrics_matlab.csv, backtest_predictions_matlab.csv and
% backtest_comparison.md (side by side with reports/backtest_metrics.csv from Python).

root = fileparts(fileparts(mfilename('fullpath')));
outDir = fullfile(root, 'reports', 'matlab');
if ~isfolder(outDir), mkdir(outDir); end

cfg.capacity = 117;
cfg.dailyTargets = ["use_total_m3", "use_pwa_chonburi_m3"];
cfg.windowTargets = ["use_total_m3", "use_pwa_chonburi_m3", "use_thai_oil_m3", "use_egat_bangpakong_m3"];
cfg.horizons = 1:7;
cfg.windows = [7 28];
cfg.storageH = [7 30 90];
cfg.demandTestStart = datetime(2022, 1, 1);
cfg.storageTestStart = datetime(2019, 1, 1);

T = readtimetable(fullfile(root, 'data', 'clean', 'bangphra_daily.csv'));
T = retime(T, 'daily');
fprintf('Loaded %d days, %s to %s\n', height(T), string(T.Properties.RowTimes(1)), string(T.Properties.RowTimes(end)));

parts = {};
runStart = tic;
for col = cfg.dailyTargets
    t0 = tic;
    [F, feats] = dailyProduct(T, col, cfg);
    parts{end+1} = fitAndPredict(F, feats, col, "daily", cfg.demandTestStart, calmonths(3), "log"); %#ok<SAGROW>
    fprintf('daily  %-24s %6.0f s\n', col, toc(t0));
end
for col = cfg.windowTargets
    t0 = tic;
    [F, feats] = windowProduct(T, col, cfg);
    parts{end+1} = fitAndPredict(F, feats, col, "window", cfg.demandTestStart, calmonths(3), "ratio"); %#ok<SAGROW>
    fprintf('window %-24s %6.0f s\n', col, toc(t0));
end
t0 = tic;
[F, feats] = storageProduct(T, cfg);
parts{end+1} = fitAndPredict(F, feats, "storage_mcm", "storage", cfg.storageTestStart, calyears(1), "delta");
fprintf('storage %31.0f s\n', toc(t0));
runSeconds = toc(runStart);

Pred = vertcat(parts{:});
M = scoreAll(Pred, cfg.capacity);
writetable(M, fullfile(outDir, 'backtest_metrics_matlab.csv'));
P = Pred;
P.origin = string(P.origin, 'yyyy-MM-dd');
P.target_date = string(P.target_date, 'yyyy-MM-dd');
writetable(P, fullfile(outDir, 'backtest_predictions_matlab.csv'));

Py = readtable(fullfile(root, 'reports', 'backtest_metrics.csv'), 'TextType', 'string');
writeComparison(M, Py, fullfile(outDir, 'backtest_comparison.md'), runSeconds, cfg);
fprintf('Done in %.0f s. Wrote %s\n', runSeconds, outDir);

%% ------------------------------------------------------------------ products

function [F, feats] = dailyProduct(T, col, cfg)
y = T.(col);
yf = fillShort(y, 3);
ma7 = rmean(yf, 7); ma28 = rmean(yf, 28); ma91 = rmean(yf, 91);
W = weather(T, cfg.capacity);
d = T.Properties.RowTimes;
n = numel(d);
blocks = cell(numel(cfg.horizons), 1);
for h = cfg.horizons
    F = table(d, d + days(h), repmat(h, n, 1), lagv(y, -h), 'VariableNames', {'origin', 'target_date', 'step', 'actual'});
    F.naive = yf;
    F.snaive_week = lagv(yf, 7 - h);
    F.ma7 = ma7;
    F.ma28 = ma28;
    F.snaive_year_scaled = lagv(yf, 364 - h) .* (ma28 ./ lagv(ma28, 364));
    % GBM features: everything relative to the last 7-day mean so trees cope with level shifts
    for k = 0:6
        F.(sprintf('lag%d_rel', k)) = lagv(yf, k) ./ ma7;
    end
    F.ma28_rel = ma28 ./ ma7;
    F.ma91_rel = ma91 ./ ma7;
    F.snaive_week_rel = lagv(yf, 7 - h) ./ ma7;
    F.year_ago_rel = lagv(yf, 364 - h) ./ lagv(ma28, 364);
    C = calendarFeatures(d + days(h));
    C.Properties.VariableNames = "tgt_" + C.Properties.VariableNames;
    F = [F, C, W]; %#ok<AGROW>
    F.h = repmat(h, n, 1);
    F.scale = ma7;
    F.yrel = log(F.actual ./ ma7);
    blocks{h} = F;
end
F = vertcat(blocks{:});
F = F(isfinite(F.scale) & F.scale > 0, :);
feats = [compose("lag%d_rel", 0:6), "ma28_rel", "ma91_rel", "snaive_week_rel", "year_ago_rel", ...
         string(C.Properties.VariableNames), string(W.Properties.VariableNames), "h"];
end

function [F, feats] = windowProduct(T, col, cfg)
y = T.(col);
yf = fillShort(y, 3);
ma28 = rmean(yf, 28); ma91 = rmean(yf, 91);
W = weather(T, cfg.capacity);
d = T.Properties.RowTimes;
n = numel(d);
blocks = cell(numel(cfg.windows), 1);
for i = 1:numel(cfg.windows)
    w = cfg.windows(i);
    fut = lagv(movsum(yf, [0 w-1], 'Endpoints', 'fill'), -1);      % sum of the next w days
    F = table(d, d + days(w), repmat(w, n, 1), fut, 'VariableNames', {'origin', 'target_date', 'step', 'actual'});
    F.naive = rsum(yf, w);                                           % last w days
    F.ma28 = ma28 * w;
    F.ma91 = ma91 * w;
    g = ma91 ./ lagv(ma91, 364);
    bad = ~isfinite(g);
    g = min(max(g, 0.25), 4);
    g(bad) = NaN;
    F.snaive_year_scaled = lagv(fut, 364) .* g;
    scale = ma91 * w;
    F.last_W_rel = F.naive ./ scale;
    F.ma28_rel = F.ma28 ./ scale;
    F.year_ago_rel = lagv(fut, 364) ./ (lagv(ma91, 364) * w);
    F.zero_share_28 = movmean(double(yf == 0), [27 0], 'Endpoints', 'fill');
    C = calendarFeatures(d + days(floor(w / 2)));
    F.tgt_month = C.month;
    F.tgt_doy_sin = C.doy_sin;
    F.tgt_doy_cos = C.doy_cos;
    F = [F, W]; %#ok<AGROW>
    F.W = repmat(w, n, 1);
    F.scale = scale;
    F.yrel = F.actual ./ scale;
    blocks{i} = F;
end
F = vertcat(blocks{:});
F = F(isfinite(F.scale) & F.scale > 0, :);
feats = ["last_W_rel", "ma28_rel", "year_ago_rel", "zero_share_28", "tgt_month", "tgt_doy_sin", ...
         "tgt_doy_cos", string(W.Properties.VariableNames), "W"];
end

function [F, feats] = storageProduct(T, cfg)
s = fillShort(T.storage_mcm, 3);
W = weather(T, cfg.capacity);
use = rmean(fillShort(T.use_total_m3, 3), 28) / 1e6;
div = rmean(T.div_in_total_m3, 28) / 1e6;
ds = [NaN; diff(s)];
d = T.Properties.RowTimes;
n = numel(d);
C = calendarFeatures(d);
blocks = cell(numel(cfg.storageH), 1);
for i = 1:numel(cfg.storageH)
    H = cfg.storageH(i);
    F = table(d, d + days(H), repmat(H, n, 1), lagv(s, -H), 'VariableNames', {'origin', 'target_date', 'step', 'actual'});
    F.now = s;
    F.dS = F.actual - s;
    F.trend7 = s + H * rmean(ds, 7);
    F.naive = s;
    F.ds7 = rsum(ds, 7);
    F.ds30 = rsum(ds, 30);
    F.use28 = use;
    F.div28 = div;
    F.doy_sin = C.doy_sin;
    F.doy_cos = C.doy_cos;
    F.month = C.month;
    F = [F, W]; %#ok<AGROW>
    F.H = repmat(H, n, 1);
    F.doy = day(d, 'dayofyear');
    blocks{i} = F;
end
F = vertcat(blocks{:});
F.yrel = F.dS;

% Climatology: mean change for the same time of year in training years only, per scored block
F.climatology = nan(height(F), 1);
starts = cfg.storageTestStart:calyears(1):max(F.origin);
for b = 1:numel(starts)
    q = starts(b);
    if b < numel(starts), qEnd = starts(b + 1); else, qEnd = max(F.origin) + days(1); end
    test = F.origin >= q & F.origin < qEnd;
    for H = cfg.storageH
        tr = F.target_date < q & F.H == H & isfinite(F.dS);
        clim = accumarray(F.doy(tr), F.dS(tr), [366 1], @mean, NaN);
        clim = movmean(clim, 15, 'omitnan');
        rows = test & F.H == H;
        F.climatology(rows) = F.now(rows) + clim(F.doy(rows));
    end
end
feats = ["now", "ds7", "ds30", "use28", "div28", "doy_sin", "doy_cos", "month", ...
         string(W.Properties.VariableNames), "H"];
end

%% ------------------------------------------------------------------ fitting

function out = fitAndPredict(F, feats, series, product, testStart, block, link)
% Retrain at the start of each block on rows whose target date is before it, then add
% P10/P90 from the residuals of earlier blocks whose actuals were already known.
X = F{:, feats};
X(isinf(X)) = NaN;
yT = F.yrel;
starts = (testStart - block):block:max(F.origin);           % first block is the warm-up
pred = nan(height(F), 1);
blockOf = zeros(height(F), 1);
for b = 1:numel(starts)
    q = starts(b);
    if b < numel(starts), qEnd = starts(b + 1); else, qEnd = max(F.origin) + days(1); end
    tr = F.target_date < q & isfinite(yT);
    te = F.origin >= q & F.origin < qEnd;
    if ~any(te) || nnz(tr) < 500, continue; end
    mdl = fitGbm(X(tr, :), yT(tr));
    pred(te) = predict(mdl, X(te, :));
    blockOf(te) = b;
end

lo = nan(height(F), 1);
hi = nan(height(F), 1);
res = yT - pred;
for b = 2:numel(starts)
    q = starts(b);
    for st = unique(F.step)'
        pool = blockOf > 0 & blockOf < b & F.step == st & F.target_date < q & isfinite(res);
        rows = blockOf == b & F.step == st;
        if nnz(pool) < 30 || ~any(rows), continue; end
        qs = quantile(res(pool), [0.1 0.9]);
        lo(rows) = pred(rows) + qs(1);
        hi(rows) = pred(rows) + qs(2);
    end
end

switch link
    case "log",   toLevel = @(z) exp(z) .* F.scale;
    case "ratio", toLevel = @(z) z .* F.scale;
    case "delta", toLevel = @(z) F.now + z;
end
F.gbm = toLevel(pred);
F.gbm_p10 = toLevel(lo);
F.gbm_p90 = toLevel(hi);

keep = F.origin >= testStart & blockOf > 0;
models = ["naive", "snaive_week", "ma7", "ma28", "ma91", "snaive_year_scaled", "trend7", "climatology", "gbm"];
out = F(keep, {'origin', 'target_date', 'step', 'actual'});
out = addvars(out, repmat(series, height(out), 1), repmat(product, height(out), 1), ...
              'Before', 1, 'NewVariableNames', {'series', 'product'});
for m = models
    if ismember(m, F.Properties.VariableNames), out.(m) = F.(m)(keep); else, out.(m) = nan(height(out), 1); end
end
out.gbm_p10 = F.gbm_p10(keep);
out.gbm_p90 = F.gbm_p90(keep);
end

function m = fitGbm(X, y)
% Mirrors the Python HistGradientBoosting settings: 300 rounds, rate 0.05, 31 leaves, min leaf 40
t = templateTree('MaxNumSplits', 30, 'MinLeafSize', 40, 'Surrogate', 'off');
m = fitrensemble(X, y, 'Method', 'LSBoost', 'NumLearningCycles', 300, 'LearnRate', 0.05, ...
                 'Learners', t, 'NumBins', 64);
end

%% ------------------------------------------------------------------ scoring and report

function M = scoreAll(Pred, capacity)
models = ["naive", "snaive_week", "ma7", "ma28", "ma91", "snaive_year_scaled", "trend7", "climatology", "gbm"];
[G, keys] = findgroups(Pred(:, {'series', 'product', 'step'}));
rows = {};
for g = 1:height(keys)
    sub = Pred(G == g & isfinite(Pred.actual), :);
    for m = models
        ok = isfinite(sub.(m));
        if ~any(ok), continue; end
        a = sub.actual(ok);
        e = sub.(m)(ok) - a;
        denom = sum(abs(a));
        cov = NaN;
        if m == "gbm"
            in = sub.actual >= sub.gbm_p10 & sub.actual <= sub.gbm_p90;
            cov = 100 * mean(in(ok & isfinite(sub.gbm_p10)));
        end
        rows(end+1, :) = {keys.series(g), keys.product(g), keys.step(g), m, nnz(ok), ...
            100 * sum(abs(e)) / denom, 100 * sum(e) / denom, mean(abs(e)), sqrt(mean(e.^2)), cov}; %#ok<AGROW>
    end
end
M = cell2table(rows, 'VariableNames', {'series', 'product', 'step', 'model', 'n', 'wape_pct', 'bias_pct', ...
                                       'mae', 'rmse', 'p10_p90_coverage_pct'});
M.series = string(M.series);
M.product = string(M.product);
M.model = string(M.model);
naive = M(M.model == "naive", {'series', 'product', 'step', 'mae'});
naive.Properties.VariableNames{'mae'} = 'naive_mae';
M = outerjoin(M, naive, 'Keys', {'series', 'product', 'step'}, 'MergeKeys', true, 'Type', 'left');
M.skill_vs_naive_pct = 100 * (1 - M.mae ./ M.naive_mae);
M.naive_mae = [];
M.mae_pct_capacity = nan(height(M), 1);
st = M.series == "storage_mcm";
M.mae_pct_capacity(st) = 100 * M.mae(st) / capacity;
end

function writeComparison(M, Py, file, runSeconds, cfg)
labels = dictionary(["use_total_m3", "use_pwa_chonburi_m3", "use_thai_oil_m3", "use_egat_bangpakong_m3", "storage_mcm"], ...
                    ["Total use", "PWA Chonburi", "Thai Oil", "EGAT Bang Pakong", "Storage"]);
J = innerjoin(M, Py, 'Keys', {'series', 'product', 'step', 'model'});
base = J(J.model ~= "gbm", :);
dW = abs(base.wape_pct_M - base.wape_pct_Py);
dN = abs(base.n_M - base.n_Py);

L = strings(0, 1);
L(end+1) = "# MATLAB vs Python forecast backtest";
L(end+1) = "";
L(end+1) = sprintf("MATLAB %s, run time %.0f s. Same data, test periods (demand from %s, storage from %s), " + ...
    "baselines, features and retraining schedule as `src/backtest.py`.", version('-release'), runSeconds, ...
    string(cfg.demandTestStart, 'yyyy-MM-dd'), string(cfg.storageTestStart, 'yyyy-MM-dd'));
L(end+1) = "The GBM is `fitrensemble` (LSBoost, 300 trees, rate 0.05, 31 leaves, min leaf 40) in MATLAB and " + ...
    "`HistGradientBoostingRegressor` with the same settings in Python.";
L(end+1) = "P10-P90: Python fits quantile-loss models; MATLAB uses residual quantiles from earlier out-of-sample blocks.";
L(end+1) = "";
L(end+1) = "## Baselines reproduce Python";
L(end+1) = "";
L(end+1) = sprintf("%d baseline rows compared (series x horizon x model). Largest WAPE difference %.4f points; " + ...
    "largest difference in number of scored forecasts %d.", height(base), max(dW), max(dN));
L(end+1) = "";

for prod = ["daily", "window", "storage"]
    S = J(J.product == prod, :);
    switch prod
        case "daily",   L(end+1) = "## Daily use, 1-7 days ahead (WAPE %)";
        case "window",  L(end+1) = "## Total use over the next 7 / 28 days (WAPE %)";
        case "storage", L(end+1) = "## Storage 7 / 30 / 90 days ahead (MAE, MCM)";
    end
    L(end+1) = "";
    L(end+1) = "| series | step | best baseline | baseline | Python GBM | MATLAB GBM | Python P10-P90 cover | MATLAB P10-P90 cover | best overall (MATLAB) |";
    L(end+1) = "|---|---|---|---|---|---|---|---|---|";
    [G, keys] = findgroups(S(:, {'series', 'step'}));
    for g = 1:height(keys)
        R = S(G == g, :);
        if prod == "storage", vM = R.mae_M; vP = R.mae_Py; fmt = "%.2f"; else, vM = R.wape_pct_M; vP = R.wape_pct_Py; fmt = "%.1f"; end
        isG = R.model == "gbm";
        [~, ib] = min(vM + 1e9 * isG);
        [~, iw] = min(vM);
        L(end+1) = sprintf("| %s | %d | %s | " + fmt + " | " + fmt + " | " + fmt + " | %.0f%% | %.0f%% | %s |", ...
            labels(keys.series(g)), keys.step(g), R.model(ib), vM(ib), vP(isG), vM(isG), ...
            R.p10_p90_coverage_pct_Py(isG), R.p10_p90_coverage_pct_M(isG), R.model(iw));
    end
    L(end+1) = "";
end
L(end+1) = "Full MATLAB metrics: reports/matlab/backtest_metrics_matlab.csv. Predictions: reports/matlab/backtest_predictions_matlab.csv.";
writelines(L, file);
end

%% ------------------------------------------------------------------ helpers

function z = lagv(x, k)
% pandas shift(k): k > 0 takes past values, k < 0 future values, NaN padded
n = numel(x);
z = nan(n, 1);
if k >= 0
    z(k+1:end) = x(1:n-k);
else
    z(1:n+k) = x(1-k:end);
end
end

function z = rmean(x, n)
z = movmean(x, [n-1 0], 'Endpoints', 'fill');     % NaN until a full window, like pandas rolling(n)
end

function z = rsum(x, n)
z = movsum(x, [n-1 0], 'Endpoints', 'fill');
end

function z = fillShort(x, limit)
% pandas interpolate(limit=limit, limit_area="inside"): linear fill of the first `limit`
% values of each interior gap; leading/trailing gaps stay NaN
z = x;
gap = isnan(x);
if ~any(gap) || all(gap), return; end
t = (1:numel(x))';
full = interp1(t(~gap), x(~gap), t, 'linear');
runPos = zeros(size(x));
c = 0;
for i = 1:numel(x)
    if gap(i), c = c + 1; else, c = 0; end
    runPos(i) = c;
end
fill = gap & runPos <= limit & isfinite(full);
z(fill) = full(fill);
end

function W = weather(T, capacity)
r = T.rain_mm;
r(isnan(r)) = 0;
W = table(rsum(r, 7), rsum(r, 30), rsum(r, 90), T.storage_mcm / capacity, ...
          'VariableNames', {'rain_7', 'rain_30', 'rain_90', 'pct_full'});
end

function C = calendarFeatures(d)
doy = day(d, 'dayofyear');
md = month(d) * 100 + day(d);
% Fixed-date holidays only (Songkran, New Year); lunar holidays are not in the calendar yet
C = table(mod(weekday(d) + 5, 7), month(d), sin(2 * pi * doy / 365.25), cos(2 * pi * doy / 365.25), ...
          double((md >= 413 & md <= 415) | md >= 1231 | md <= 102), ...
          'VariableNames', {'dow', 'month', 'doy_sin', 'doy_cos', 'holiday'});
end
