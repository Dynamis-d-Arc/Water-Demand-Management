% supply_outlook.m  Bang Phra storage risk outlook by ensemble streamflow prediction (ESP).
% Run from water_poc:   matlab -batch "run('matlab/supply_outlook.m')"
%
% From a start date, storage is simulated day by day once for every past year's natural
% inflow sequence (runoff + rain on the reservoir, sheet column AF):
%   S(t+1) = S(t) + inflow + diversions - use - releases - evaporation(area(S), month)
% capped at capacity (excess spills). Operating terms are scenarios, not forecasts:
%   use         "recent" = last 28-day mean, or "plan" = sheet 3 allocation plan
%   diversions  "typical" = same days averaged over the previous 3 years, or "none"
%   releases    river/canal/agricultural outlets, same days averaged over the previous 3 years
%
% 1. Backtest (origins 2019-01-01 onward, recent use + typical diversions, only past inflow
%    years) scored like the storage forecasts in reports/matlab/backtest_metrics_matlab.csv.
% 2. Outlook from the last observed day for 180 days, for each use/diversion scenario.
% Writes reports/matlab/supply_outlook.md, supply_outlook_backtest.csv, supply_outlook_paths.csv
% (daily P10/P50/P90 and shortage probability per scenario) and supply_outlook_fan.png.

root = fileparts(fileparts(mfilename('fullpath')));
outDir = fullfile(root, 'reports', 'matlab');
if ~isfolder(outDir), mkdir(outDir); end

cap = 117;
critical = 0.3 * cap;                                      % "critical low" on sheet 1 (<= 30%)
evapRate = [4.8 5.1 5.6 5.8 5.3 5.2 5.1 5.0 4.7 4.5 4.7 5.0];   % mm/day, sheet side table AH1:AI12

T = readtimetable(fullfile(root, 'data', 'clean', 'bangphra_daily.csv'));
T = retime(T, 'daily');
curve = readtable(fullfile(root, 'data', 'clean', 'bangphra_level_storage_area.csv'));
[Sc, ia] = unique(curve.storage_mcm);
Ac = curve.area_km2(ia);
plan = readtimetable(fullfile(root, 'data', 'clean', 'bangphra_allocation_plan.csv'));

d = T.Properties.RowTimes;
S = T.storage_mcm;
inflow = T.runoff_in_m3;
inflow(isnan(inflow)) = 0;                                 % 37 days where the sheet's outflow was invalid
div = T.div_in_total_m3;
rel = T.release_river_outlet_m3 + T.release_canal_outlet_m3 + T.release_agriculture_m3;
use28 = movmean(fillmissing(T.use_total_m3, 'linear', 'MaxGap', 4), [27 0], 'Endpoints', 'fill');
model = struct('d', d, 'inflow', inflow, 'div', div, 'rel', rel, 'Sc', Sc, 'Ac', Ac, ...
               'cap', cap, 'evapRate', evapRate);

%% 1. Backtest
H = [7 30 90];
origins = d(d >= datetime(2019, 1, 1) & isfinite(S) & isfinite(use28));
rows = nan(numel(origins) * numel(H), 7);
r = 0;
for i = 1:numel(origins)
    t0 = origins(i);
    k0 = find(d == t0);
    years = year(d(1)):(year(t0) - 1);                       % only inflow years already observed
    [Sim, ok] = simulate(model, t0, S(k0), max(H), years, repmat(use28(k0), max(H), 1), "typical");
    if ~ok, continue; end
    for h = H
        if k0 + h > numel(S), continue; end
        q = quantile(Sim(h, :), [0.1 0.5 0.9]);
        r = r + 1;
        rows(r, :) = [datenum(t0), h, S(k0 + h), q, mean(Sim(h, :) < critical)];
    end
end
rows = rows(1:r, :);
B = array2table(rows, 'VariableNames', {'origin', 'step', 'actual', 'p10', 'p50', 'p90', 'prob_below_30pct'});
B.origin = datetime(B.origin, 'ConvertFrom', 'datenum');
B = B(isfinite(B.actual), :);
writetable(B, fullfile(outDir, 'supply_outlook_backtest.csv'));

Mm = readtable(fullfile(outDir, 'backtest_metrics_matlab.csv'), 'TextType', 'string');
L = strings(0, 1);
L(end+1) = "# Bang Phra supply risk outlook (ESP)";
L(end+1) = "";
L(end+1) = "Storage is simulated once for every past year's natural inflow from the start date, with use, " + ...
    "diversions and releases set by scenario (see `matlab/supply_outlook.m`). The spread across years " + ...
    "is the inflow uncertainty; operating decisions are not forecast.";
L(end+1) = "";
L(end+1) = sprintf("## Backtest (origins %s to %s, recent use + typical diversions)", ...
    string(min(B.origin), 'yyyy-MM-dd'), string(max(B.origin), 'yyyy-MM-dd'));
L(end+1) = "";
L(end+1) = "| days ahead | ESP P50 MAE (MCM) | GBM MAE | climatology MAE | ESP P10-P90 cover | GBM P10-P90 cover | ESP bias (MCM) |";
L(end+1) = "|---|---|---|---|---|---|---|";
for h = H
    b = B(B.step == h, :);
    g = Mm(Mm.series == "storage_mcm" & Mm.step == h, :);
    L(end+1) = sprintf("| %d | %.2f | %.2f | %.2f | %.0f%% | %.0f%% | %+.2f |", h, mean(abs(b.p50 - b.actual)), ...
        g.mae(g.model == "gbm"), g.mae(g.model == "climatology"), ...
        100 * mean(b.actual >= b.p10 & b.actual <= b.p90), g.p10_p90_coverage_pct(g.model == "gbm"), ...
        mean(b.p50 - b.actual));
end
L(end+1) = "";
L(end+1) = sprintf("Shortage warning, storage below 30%% of capacity (%.1f MCM) at the horizon:", critical);
L(end+1) = "";
L(end+1) = "| days ahead | days observed below 30% | mean forecast probability | Brier score | Brier skill vs base rate |";
L(end+1) = "|---|---|---|---|---|";
train = d < datetime(2019, 1, 1) & isfinite(S);
base = mean(S(train) < critical);
for h = H
    b = B(B.step == h, :);
    o = double(b.actual < critical);
    bs = mean((b.prob_below_30pct - o).^2);
    bsRef = mean((base - o).^2);
    L(end+1) = sprintf("| %d | %d of %d | %.2f | %.3f | %.2f |", h, sum(o), numel(o), mean(b.prob_below_30pct), bs, 1 - bs / bsRef);
end
L(end+1) = "";
L(end+1) = sprintf("Base rate = share of days below 30%% in 1990-2018 (%.0f%%). Skill > 0 beats always forecasting that rate.", 100 * base);
L(end+1) = "";

%% 2. Outlook from the last observed day
t0 = d(find(isfinite(S), 1, 'last'));
k0 = find(d == t0);
N = 180;
fut = t0 + days(0:N-1)';
planUse = interp1(plan.Properties.RowTimes, plan.plan_use_total_m3, fut, 'previous', 'extrap');
scen = struct('name', {"Recent use, typical diversions", "Recent use, no diversions", ...
                       "Allocation plan, typical diversions", "Allocation plan, no diversions"}, ...
              'use', {repmat(use28(k0), N, 1), repmat(use28(k0), N, 1), planUse, planUse}, ...
              'div', {"typical", "none", "typical", "none"});
years = year(d(1)):(year(t0) - 1);
L(end+1) = sprintf("## Outlook from %s (storage %.1f MCM, %.0f%% full) for %d days", ...
    string(t0, 'yyyy-MM-dd'), S(k0), 100 * S(k0) / cap, N);
L(end+1) = "";
L(end+1) = sprintf("Recent use = %.0f m3/day (28-day mean). Plan use = sheet 3 total for each day (%.0f-%.0f m3/day). " + ...
    "%d inflow years (%d-%d).", use28(k0), min(planUse), max(planUse), numel(years), years(1), years(end));
L(end+1) = "";
L(end+1) = "| scenario | P50 at 30 d | P50 at 90 d | P10 at 90 d | P50 at 180 d | P(<30%) by 90 d | P(<30%) by 180 d | 10%-risk day below 30% |";
L(end+1) = "|---|---|---|---|---|---|---|---|";
fig = figure('Visible', 'off', 'Position', [100 100 1100 700]);
theme(fig, 'light');
tl = tiledlayout(fig, 2, 2, 'TileSpacing', 'compact');
paths = table();
for s = 1:numel(scen)
    [Sim, ok] = simulate(model, t0, S(k0), N, years, scen(s).use, scen(s).div);
    if ~ok, error('Outlook simulation failed for %s', scen(s).name); end
    q = quantile(Sim, [0.1 0.5 0.9], 2);
    pBy90 = mean(any(Sim(1:90, :) < critical, 1));
    pBy180 = mean(any(Sim < critical, 1));
    below = Sim < critical;
    paths = [paths; table(repmat(scen(s).name, N, 1), repmat(scen(s).div, N, 1), scen(s).use(:), (1:N)', ...
        string(t0 + days(1:N)', 'yyyy-MM-dd'), q(:, 1), q(:, 2), q(:, 3), mean(below, 2), mean(cummax(below, 1), 2), ...
        'VariableNames', {'scenario', 'diversions', 'use_m3_per_day', 'day', 'date', 'p10_mcm', 'p50_mcm', 'p90_mcm', ...
        'prob_below_30pct', 'prob_below_30pct_by_day'})]; %#ok<AGROW>
    first = find(q(:, 1) < critical, 1);
    if isempty(first), firstTxt = "not within 180 d"; else, firstTxt = string(fut(first) + days(1), 'yyyy-MM-dd'); end
    L(end+1) = sprintf("| %s | %.1f | %.1f | %.1f | %.1f | %.0f%% | %.0f%% | %s |", scen(s).name, q(30, 2), q(90, 2), ...
        q(90, 1), q(N, 2), 100 * pBy90, 100 * pBy180, firstTxt);

    ax = nexttile(tl);
    hold(ax, 'on');
    x = (1:N)';
    fill(ax, [x; flipud(x)], [q(:, 1); flipud(q(:, 3))], [0.16 0.44 0.69], 'FaceAlpha', 0.2, 'EdgeColor', 'none');
    plot(ax, x, q(:, 2), 'Color', [0.16 0.44 0.69], 'LineWidth', 1.5);
    plot(ax, (-120:0)', S(k0-120:k0), 'k', 'LineWidth', 1);
    xlabel(ax, sprintf('days from %s', string(t0, 'dd MMM yyyy')));
    yline(ax, critical, ':', '30% critical', 'Color', [0.82 0.29 0.36]);
    yline(ax, cap, '--', 'capacity', 'Color', [0.5 0.5 0.5]);
    title(ax, scen(s).name, 'FontWeight', 'normal');
    ylabel(ax, 'MCM');
    ylim(ax, [0 125]);
    grid(ax, 'on');
end
title(tl, sprintf('Bang Phra storage outlook from %s (P10-P90 band, P50 line)', string(t0, 'dd MMM yyyy')));
exportgraphics(fig, fullfile(outDir, 'supply_outlook_fan.png'), 'Resolution', 110);
writetable(paths, fullfile(outDir, 'supply_outlook_paths.csv'));
L(end+1) = "";
L(end+1) = "10%-risk day = first day the P10 path drops below 30% of capacity. Figure: reports/matlab/supply_outlook_fan.png.";
L(end+1) = "";
L(end+1) = "Assumptions: evaporation = surface area x the sheet's monthly pan rate; diversions and outlet releases are " + ...
    "averages, not responses to storage (in practice pumping in increases when storage is low); inflow years are " + ...
    "treated as equally likely (no seasonal rainfall forecast yet).";
writelines(L, fullfile(outDir, 'supply_outlook.md'));
fprintf('%s\n', L);

%% ------------------------------------------------------------------ helpers

function [Sim, ok] = simulate(m, t0, S0, N, years, use, divMode)
% Storage at the end of days 1..N (rows) for each inflow year (columns)
ok = false;
Sim = [];
seq = [];
for y = years
    ky = find(m.d == datetime(y, month(t0), min(day(t0), 28)) + (day(t0) - min(day(t0), 28)), 1);
    if isempty(ky) || ky + N - 1 > numel(m.d), continue; end
    seq(:, end+1) = m.inflow(ky:ky+N-1); %#ok<AGROW>
end
if size(seq, 2) < 10 || ~isfinite(S0), return; end
divT = typical(m, m.div, t0, N);
relT = typical(m, m.rel, t0, N);
if divMode == "none", divT(:) = 0; end
months = month(t0 + days(0:N-1)');
s = repmat(S0, 1, size(seq, 2));
Sim = nan(N, size(seq, 2));
for k = 1:N
    A = interp1(m.Sc, m.Ac, min(max(s, m.Sc(1)), m.Sc(end)));
    ev = A * m.evapRate(months(k)) * 1000;                  % km2 x mm/day -> m3/day
    s = s + (seq(k, :) + divT(k) - use(k) - relT(k) - ev) / 1e6;
    s = min(max(s, 0), m.cap);
    Sim(k, :) = s;
end
ok = true;
end

function v = typical(m, x, t0, N)
% Same calendar days averaged over the 3 years before t0
acc = zeros(N, 1);
n = 0;
for back = 1:3
    ky = find(m.d == t0 - calyears(back), 1);
    if isempty(ky) || ky + N - 1 > numel(m.d), continue; end
    seg = x(ky:ky+N-1);
    seg(isnan(seg)) = 0;
    acc = acc + seg;
    n = n + 1;
end
v = acc / max(n, 1);
end
