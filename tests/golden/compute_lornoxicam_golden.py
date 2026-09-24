"""Lornoxicam 골든 값 재계산 (v6.1).

정책 (v6.1):
- 전체 이차모형으로 적합, 마손도는 연구자 승인 선형 축소를 적용
- supported domain = BBD 설계점의 convex hull (coded: |xi|<=1, |a|+|b|+|c|<=2)
- feasible 비율의 분모 = domain 안의 격자점
- 공동확률 = 반응별 t 예측분포 확률의 곱 (독립 가정)
- 확인점 PI = family(필수 확인점 × DOE_RESPONSE) Bonferroni 동시구간
- 규격(연구자 입력 가정 포함): Y1<=180 s, Y2<=1.0 %, Y3>=75 %, Y4<=15
"""
import sys, pathlib, numpy as np, pandas as pd, statsmodels.formula.api as smf
from scipy import stats
p = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "lornoxicam_table3.csv"
d = pd.read_csv(p).rename(columns={"y1_dispersibility_s":"Y1","y2_friability_pct":"Y2","y3_de30_pct":"Y3","y4_cu_av":"Y4"})
d["a"] = d.x1_mcc_mannitol_ratio - 2; d["b"] = (d.x2_mixing_time_min - 10) / 5; d["c"] = (d.x3_crospovidone_pct - 6) / 4
Q = "a+b+c+a:b+a:c+b:c+I(a**2)+I(b**2)+I(c**2)"
full = {y: smf.ols(f"{y}~{Q}", d).fit() for y in ["Y1","Y2","Y3","Y4"]}
M = dict(full); M["Y2"] = smf.ols("Y2~a+b+c", d).fit()   # 연구자 승인 축소
spec = {"Y1":("le",180), "Y2":("le",1.0), "Y3":("ge",75), "Y4":("le",15)}

def pred_R2(m):
    h = m.get_influence().hat_matrix_diag
    return 1 - ((m.resid/(1-h))**2).sum() / ((m.model.endog - m.model.endog.mean())**2).sum()

out = {}
for y in ["Y1","Y2","Y3","Y4"]:
    out[f"{y}_full_R2"] = full[y].rsquared; out[f"{y}_full_predR2"] = pred_R2(full[y])
out["Y2_linear_R2"] = M["Y2"].rsquared; out["Y2_linear_predR2"] = pred_R2(M["Y2"])
cd = full["Y1"].get_influence().cooks_distance[0]; out["Y1_maxCook_run"] = int(np.argmax(cd)) + 1; out["Y1_maxCook"] = cd.max()

g = np.linspace(-1, 1, 21); A, B, C = np.meshgrid(g, g, g, indexing="ij")
G = pd.DataFrame({"a":A.ravel(), "b":B.ravel(), "c":C.ravel()})
G["in_domain"] = (G.a.abs() + G.b.abs() + G.c.abs()) <= 2 + 1e-9
P = np.ones(len(G)); mean_ok = np.ones(len(G), bool); binding = {}
for y,(op,L) in spec.items():
    m = M[y]; pr = m.get_prediction(G).summary_frame(); mu = pr["mean"].values
    s = np.sqrt(pr["mean_se"].values**2 + m.scale)
    pp = stats.t.cdf((L-mu)/s, m.df_resid) if op == "le" else 1 - stats.t.cdf((L-mu)/s, m.df_resid)
    P *= pp; mean_ok &= (mu <= L) if op == "le" else (mu >= L); G["p"+y] = pp
G["P"] = P
D = G[G.in_domain]
out["grid_points_total"] = len(G); out["grid_points_in_domain"] = len(D)
out["mean_ok_fraction_in_domain"] = mean_ok[G.in_domain.values].mean()
out["joint_P090_fraction_in_domain"] = (D.P >= 0.90).mean()
out["binding_cqa_counts"] = D[D.P < 0.90][["pY1","pY2","pY3","pY4"]].idxmin(axis=1).value_counts().to_dict()

def edge_dist(r):  # coded 거리: 면 |xi|=1 과 평면 sum|x|=2
    return min(1-abs(r.a), 1-abs(r.b), 1-abs(r.c), (2-(abs(r.a)+abs(r.b)+abs(r.c)))/np.sqrt(3))
D = D.assign(edge=D.apply(edge_dist, axis=1))
cand = D[D.edge >= 0.1]; i = cand.P.idxmax()
out["setpoint_coded"] = (G.a[i], G.b[i], G.c[i])
out["setpoint_actual"] = (round(2+G.a[i],2), round(10+5*G.b[i],2), round(6+4*G.c[i],2)); out["setpoint_P"] = G.P[i]

m_family = 3 * 4; level = 1 - 0.05 / m_family
out["verification_family_size"] = m_family; out["per_comparison_PI_level"] = level
def pi(x1,x2,x3):
    row = pd.DataFrame({"a":[x1-2], "b":[(x2-10)/5], "c":[(x3-6)/4]}); r = {}
    for y in spec:
        f = M[y].get_prediction(row).summary_frame(alpha=1-level)
        r[y] = (round(f["mean"].iloc[0],2), round(f.obs_ci_lower.iloc[0],2), round(f.obs_ci_upper.iloc[0],2))
    return r
out["PI_setpoint"] = pi(*out["setpoint_actual"])
out["PI_reference_existing_3.0_11_6.23"] = pi(3.0, 11, 6.23)
for k, v in out.items():
    print(f"{k}: {np.round(v,3) if isinstance(v,float) else v}")
