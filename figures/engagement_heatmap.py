# ════════════════════════════════════════════════════════════════════════════
# 5.4 — Behavioural engagement: correlation heatmap
# ════════════════════════════════════════════════════════════════════════════
import seaborn as sns
from scipy.stats import spearmanr

OUTCOME       = "test_kendall_tau_total"
OUTCOME_LABEL = "Ranking\nquality (τ)"

VARS_ALL = {
    "train_duration_sec":         "Training\nduration (s)",
    "test_duration_sec":          "Test\nduration (s)",
    "test_rule_consult":          "Rule\nconsultations",
    "test_correction_time_total": "Correction\nscreen time (s)",
}

# ── Build correlation matrix (predictors + outcome) ───────────────────────────
def build_corr_df(data, var_dict, outcome, outcome_label):
    cols   = list(var_dict.keys()) + [outcome]
    labels = list(var_dict.values()) + [outcome_label]
    sub    = data[cols].dropna()
    n      = len(sub)
    k      = len(cols)
    mat_r  = np.zeros((k, k))
    mat_p  = np.zeros((k, k))
    for i in range(k):
        for j in range(k):
            if i == j:
                mat_r[i, j] = 1.0
                mat_p[i, j] = 0.0
            else:
                r, p = spearmanr(sub.iloc[:, i], sub.iloc[:, j])
                mat_r[i, j] = round(r, 2)
                mat_p[i, j] = round(p, 3)
    return (pd.DataFrame(mat_r, index=labels, columns=labels),
            pd.DataFrame(mat_p, index=labels, columns=labels),
            n)

mat_r, mat_p, n = build_corr_df(
    df_duration, VARS_ALL, OUTCOME, OUTCOME_LABEL)

# ── Annotation: rₛ + significance star ───────────────────────────────────────
def annot_matrix(r_df, p_df):
    annot = r_df.copy().astype(str)
    for i in r_df.index:
        for j in r_df.columns:
            r = r_df.loc[i, j]
            p = p_df.loc[i, j]
            if i == j:
                annot.loc[i, j] = "1.00"
            else:
                star = "*" if p < .05 else ""
                annot.loc[i, j] = f"{r:.2f}{star}"
    return annot

annot = annot_matrix(mat_r, mat_p)

# ── Upper triangle mask ───────────────────────────────────────────────────────
k    = len(mat_r)
mask = np.zeros((k, k), dtype=bool)
mask[np.triu_indices(k, k=1)] = True

# ── Plot ──────────────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(7, 6))
fig.patch.set_facecolor("white")

cmap = sns.diverging_palette(220, 20, as_cmap=True)   # blue–white–red

sns.heatmap(
    mat_r,
    ax=ax,
    mask=mask,
    cmap=cmap,
    vmin=-1, vmax=1,
    annot=annot,
    fmt="",
    annot_kws={"size": 9},
    linewidths=0.5,
    linecolor="#eeeeee",
    cbar=True,
    square=True,
)

ax.collections[0].colorbar.set_label("Spearman rₛ", fontsize=9)
ax.set_title(f"All participants  (N = {n})", fontsize=11,
             color="#333333", pad=10)
ax.tick_params(axis="x", rotation=30, labelsize=8)
ax.tick_params(axis="y", rotation=0,  labelsize=8)

fig.suptitle(
    "Spearman correlations — behavioural engagement variables\n"
    "and ranking quality (τ total).  * p < .05",
    fontsize=10, color="#444444", y=1.02
)

plt.tight_layout()
plt.savefig("engagement_heatmap.png", dpi=180,
            bbox_inches="tight", facecolor="white")
plt.show()

# ── Print correlation table for reference ─────────────────────────────────────
print(f"\nSpearman correlations with τ_total  (N={n})")
print("-" * 55)
for col, label in VARS_ALL.items():
    valid    = df_duration[[col, OUTCOME]].dropna()
    r, p     = spearmanr(valid[col], valid[OUTCOME])
    sig      = "n.s." if p > .05 else "*"
    print(f"  {label.replace(chr(10),' '):<35} rₛ={r:+.3f}  p={p:.3f}  {sig}")
