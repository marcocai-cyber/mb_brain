import sys, math, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fair_speciali as F

ok = True
def chk(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print("OK " if cond else "XX ", name, info)

# 1) calibrazione: un modello noto deve essere ritrovato dalle sue stesse quote
true = F.MatchModel(1.65, 0.95, -0.06, 0.44)
s = true.summary()
targets = {"1x2": (s["1"], s["X"], s["2"]), "ou": {1.5: s["over1.5"], 2.5: s["over2.5"], 3.5: s["over3.5"]},
           "btts": s["btts"]}
t0 = time.time()
fit = F.MatchModel.fit(targets)
chk("fit lambda casa", abs(fit.lh - 1.65) < 0.03, repr(fit))
chk("fit lambda ospite", abs(fit.la - 0.95) < 0.03)
chk("fit rho", abs(fit.rho + 0.06) < 0.03, f"{time.time()-t0:.2f}s")

# 2) stati tempo per tempo coerenti con la distribuzione finale
m = F.MatchModel(1.4, 1.1, 0.0, 0.45)
p_over25 = F.prob_leg(m, [{"t": "gol", "chi": "tot", "min": 3}])
exact = 1 - sum(math.exp(-2.5) * 2.5 ** k / math.factorial(k) for k in range(3))
chk("over 2.5 da stati = Poisson", abs(p_over25 - exact) < 1e-4, f"{p_over25:.5f} vs {exact:.5f}")

# 3) over 0.5 1T + over 0.5 2T: con Poisson indipendenti e' il prodotto
p = F.prob_leg(m, [{"t": "gol", "chi": "tot", "tempo": "1t", "min": 1}, {"t": "gol", "chi": "tot", "tempo": "2t", "min": 1}])
exp_ = (1 - math.exp(-2.5 * 0.45)) * (1 - math.exp(-2.5 * 0.55))
chk("over 0.5 entrambi i tempi", abs(p - exp_) < 1e-4, f"{p:.4f}")

# 4) marcatore: con quota gol s, P(segna) = 1 - exp(-lambda_squadra * s)
g = {"Rossi": {"chi": "casa", "quota_gol": 0.3, "quota_assist": 0.2, "p_cartellino": 0.2}}
p = F.prob_leg(m, [{"t": "giocatore", "nome": "Rossi", "chi": "casa", "cosa": "segna"}], g)
chk("marcatore = 1-exp(-l*s)", abs(p - (1 - math.exp(-1.4 * 0.3))) < 1e-4, f"{p:.4f}")
# due marcatori stessa squadra: indipendenti nel modello di Poisson
g["Bianchi"] = {"chi": "casa", "quota_gol": 0.2, "quota_assist": 0.1, "p_cartellino": 0.1}
p2 = F.prob_leg(m, [{"t": "giocatore", "nome": "Rossi", "chi": "casa", "cosa": "segna"},
                    {"t": "giocatore", "nome": "Bianchi", "chi": "casa", "cosa": "segna"}], g)
chk("due marcatori stessa squadra", abs(p2 - (1 - math.exp(-0.42)) * (1 - math.exp(-0.28))) < 1e-4, f"{p2:.4f}")
# marcatore + vittoria della sua squadra > prodotto delle due (correlazione positiva)
pw = F.prob_leg(m, [{"t": "esito", "sel": ["1"]}])
pj = F.prob_leg(m, [{"t": "esito", "sel": ["1"]}, {"t": "giocatore", "nome": "Rossi", "chi": "casa", "cosa": "segna"}], g)
chk("marcatore+1 correlati", pj > pw * p, f"{pj:.4f} > {pw*p:.4f}")
# primo marcatore: somma su tutti i 'giocatori' della squadra = P(primo gol casa)
pf = F.prob_leg(m, [{"t": "giocatore", "nome": "Rossi", "chi": "casa", "cosa": "primo"}], g)
pfc = F.prob_leg(m, [{"t": "primo_gol_squadra", "chi": "casa"}])
chk("primo marcatore = quota * P(primo gol squadra)", abs(pf - 0.3 * pfc) < 1e-6, f"{pf:.4f}")
chk("P(primo gol casa) ~ l_casa/l_tot*(1-e^-l)", abs(pfc - 1.4 / 2.5 * (1 - math.exp(-2.5))) < 2e-3, f"{pfc:.4f}")
# goal o assist
pga = F.prob_leg(m, [{"t": "giocatore", "nome": "Rossi", "chi": "casa", "cosa": "segna_o_assist"}], g)
chk("goal o assist", abs(pga - (1 - math.exp(-1.4 * 0.5))) < 1e-4, f"{pga:.4f}")

# 5) vince almeno un tempo / segna in entrambi i tempi sensati
pv = F.prob_leg(m, [{"t": "vince_un_tempo", "chi": "ospite"}])
chk("vince almeno un tempo in (P(2), 1)", F.prob_leg(m, [{"t": "esito", "sel": ["2"]}]) < pv < 0.7, f"{pv:.4f}")
# 6) multigol casa 2-3
pm = F.prob_leg(m, [{"t": "gol", "chi": "casa", "min": 2, "max": 3}])
ex = sum(math.exp(-1.4) * 1.4 ** k / math.factorial(k) for k in (2, 3))
chk("multigol casa 2-3", abs(pm - ex) < 1e-4, f"{pm:.4f}")
sys.exit(0 if ok else 1)
