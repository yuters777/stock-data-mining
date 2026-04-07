# PEAD Entry-Corrected Retest (CC-PEAD-2)

Fixes measurement bug: returns now computed from event_close (when signal is known), not prior_close.

## Step 3: Corrected Config Results

| Config                |   N |   Mean% |   Med% |   WR% |   PF |   p-val |   Losers |   MaxLoss% |
|:----------------------|----:|--------:|-------:|------:|-----:|--------:|---------:|-----------:|
| SHORT_g1_fb_ec_nc     | 110 |   0.15  | -0.03  |  48.2 | 1.13 |    0.69 |       57 |     -18.57 |
| SHORT_g1_fb_no_nc     | 110 |   0.186 |  0.027 |  50.9 | 1.18 |    0.53 |       54 |      -9.53 |
| SHORT_g3_fb_ec_nc     |  52 |   0.421 |  0.83  |  55.8 | 1.38 |    0.45 |       23 |     -18.57 |
| SHORT_g1_fb_ec_nc_adj | 110 |   0.259 | -0.037 |  49.1 | 1.27 |    0.47 |       56 |     -18.07 |
| LONG_g2_fb_5d_corr    |  64 |   0.402 |  0.523 |  56.2 | 1.14 |    0.69 |       28 |     -21.63 |
| LONG_g3_fb_5d_corr    |  50 |   0.664 |  1.291 |  62   | 1.24 |    0.55 |       19 |     -21.63 |
| BOTH_g3_fb_3d_corr    | 102 |   0.377 | -0.086 |  50   | 1.15 |    0.62 |       51 |     -26.88 |

## Step 2/6: AMC vs BMO Breakdown

### SHORT_g1_fb_ec_nc

| ToD   |   N |   Mean% |   WR% |   PF |
|:------|----:|--------:|------:|-----:|
| AMC   |  71 |   0.083 |  43.7 | 1.06 |
| BMO   |  39 |   0.273 |  56.4 | 1.48 |
| ALL   | 110 |   0.15  |  48.2 | 1.13 |

### SHORT_g1_fb_no_nc

| ToD   |   N |   Mean% |   WR% |   PF |
|:------|----:|--------:|------:|-----:|
| AMC   |  71 |   0.271 |  53.5 | 1.22 |
| BMO   |  39 |   0.031 |  46.2 | 1.05 |
| ALL   | 110 |   0.186 |  50.9 | 1.18 |

### SHORT_g3_fb_ec_nc

| ToD   |   N |   Mean% |   WR% |   PF |
|:------|----:|--------:|------:|-----:|
| AMC   |  29 |   0.333 |  55.2 | 1.22 |
| BMO   |  23 |   0.533 |  56.5 | 1.9  |
| ALL   |  52 |   0.421 |  55.8 | 1.38 |

### SHORT_g1_fb_ec_nc_adj

| ToD   |   N |   Mean% |   WR% |   PF |
|:------|----:|--------:|------:|-----:|
| AMC   |  71 |   0.251 |  47.9 | 1.22 |
| BMO   |  39 |   0.274 |  51.3 | 1.45 |
| ALL   | 110 |   0.259 |  49.1 | 1.27 |

### LONG_g2_fb_5d_corr

| ToD   |   N |   Mean% |   WR% |   PF |
|:------|----:|--------:|------:|-----:|
| AMC   |  42 |   0.674 |  54.8 | 1.23 |
| BMO   |  22 |  -0.117 |  59.1 | 0.96 |
| ALL   |  64 |   0.402 |  56.2 | 1.14 |

### LONG_g3_fb_5d_corr

| ToD   |   N |   Mean% |   WR% |   PF |
|:------|----:|--------:|------:|-----:|
| AMC   |  30 |   0.856 |    60 | 1.32 |
| BMO   |  20 |   0.378 |    65 | 1.14 |
| ALL   |  50 |   0.664 |    62 | 1.24 |

### BOTH_g3_fb_3d_corr

| ToD   |   N |   Mean% |   WR% |   PF |
|:------|----:|--------:|------:|-----:|
| AMC   |  59 |   0.068 |  42.4 | 1.02 |
| BMO   |  43 |   0.801 |  60.5 | 1.48 |
| ALL   | 102 |   0.377 |  50   | 1.15 |

## Step 4: Corrected Bootstrap

| config                |   N |   actual% |   rand% |   rand_std% |   pctile |   boot_p |
|:----------------------|----:|----------:|--------:|------------:|---------:|---------:|
| SHORT_g3_fb_ec_nc     |  52 |     0.421 |  -0.135 |       0.595 |     83.1 |    0.339 |
| SHORT_g1_fb_ec_nc_adj | 110 |     0.259 |  -0.037 |       0.364 |     79.2 |    0.416 |
| LONG_g3_fb_5d_corr    |  50 |     0.664 |   0.448 |       1.142 |     58.3 |    0.835 |

## Step 5: Corrected LOTO + LOYO + IS/OOS

No configs pass N>=20 + PF>=1.5 for robustness testing.

## Step 7: Overnight vs Intraday Decomposition

### SHORT_g1_fb_ec_nc (N=110)

| window            |   N |   mean% |   WR% |   PF |
|:------------------|----:|--------:|------:|-----:|
| Overnight (ec→no) | 110 |  -0.046 |  50   | 0.95 |
| Intraday (no→nc)  | 110 |   0.186 |  50.9 | 1.18 |
| Total (ec→nc)     | 110 |   0.15  |  48.2 | 1.13 |

Edge source: **INTRADAY** (overnight: 20%)

### SHORT_g1_fb_no_nc (N=110)

| window            |   N |   mean% |   WR% |   PF |
|:------------------|----:|--------:|------:|-----:|
| Overnight (ec→no) | 110 |  -0.046 |  50   | 0.95 |
| Intraday (no→nc)  | 110 |   0.186 |  50.9 | 1.18 |
| Total (ec→nc)     | 110 |   0.15  |  48.2 | 1.13 |

Edge source: **INTRADAY** (overnight: 20%)

### SHORT_g3_fb_ec_nc (N=52)

| window            |   N |   mean% |   WR% |   PF |
|:------------------|----:|--------:|------:|-----:|
| Overnight (ec→no) |  52 |  -0.091 |  55.8 | 0.9  |
| Intraday (no→nc)  |  52 |   0.498 |  55.8 | 1.49 |
| Total (ec→nc)     |  52 |   0.421 |  55.8 | 1.38 |

Edge source: **INTRADAY** (overnight: 15%)

### SHORT_g1_fb_ec_nc_adj (N=110)

| window            |   N |   mean% |   WR% |   PF |
|:------------------|----:|--------:|------:|-----:|
| Overnight (ec→no) | 110 |  -0.046 |  50   | 0.95 |
| Intraday (no→nc)  | 110 |   0.186 |  50.9 | 1.18 |
| Total (ec→nc)     | 110 |   0.15  |  48.2 | 1.13 |

Edge source: **INTRADAY** (overnight: 20%)

## PEAD ENTRY-CORRECTED RETEST — FINAL VERDICT

### Contamination Check

```
Old best (SHORT_g1_fb, drift_1d from prior_close):
  N=110, Mean=5.059%, WR=84.5%, PF=25.53

Corrected (SHORT_g1_fb, event_close→next_close):
  N=110, Mean=0.150%, WR=48.2%, PF=1.13

PF degradation: 95.6%
```

### Best Corrected Configs

```

Config: SHORT_g3_fb_ec_nc
  N=52, Mean=0.421%, WR=55.8%, PF=1.38, p=0.45
  LOTO: —  |  IS/OOS: —
  OVERALL: MARGINAL

Config: SHORT_g1_fb_ec_nc_adj
  N=110, Mean=0.259%, WR=49.1%, PF=1.27, p=0.47
  LOTO: —  |  IS/OOS: —
  OVERALL: MARGINAL

Config: LONG_g3_fb_5d_corr
  N=50, Mean=0.664%, WR=62.0%, PF=1.24, p=0.55
  LOTO: —  |  IS/OOS: —
  OVERALL: MARGINAL

Config: SHORT_g1_fb_no_nc
  N=110, Mean=0.186%, WR=50.9%, PF=1.18, p=0.53
  LOTO: —  |  IS/OOS: —
  OVERALL: MARGINAL

Config: BOTH_g3_fb_3d_corr
  N=102, Mean=0.377%, WR=50.0%, PF=1.15, p=0.62
  LOTO: —  |  IS/OOS: —
  OVERALL: MARGINAL

Config: LONG_g2_fb_5d_corr
  N=64, Mean=0.402%, WR=56.2%, PF=1.14, p=0.69
  LOTO: —  |  IS/OOS: —
  OVERALL: MARGINAL

Config: SHORT_g1_fb_ec_nc
  N=110, Mean=0.150%, WR=48.2%, PF=1.13, p=0.69
  LOTO: —  |  IS/OOS: —
  OVERALL: MARGINAL
```

### Recommendation

**MARGINAL**: Corrected edge exists but is weak (PF < 1.5). Consider combining with additional filters or signals.
