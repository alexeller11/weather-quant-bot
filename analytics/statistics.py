
"""analytics.statistics (v2)"""
from __future__ import annotations
import math
from collections import defaultdict
from statistics import mean
from .dataset import TradeDataset

def _resolved(ds): return ds.wins+ds.losses


def _pairs(ds):
    """
    Pares (probabilidade prevista para O LADO APOSTADO, ganhou?).

    `model_prob` é P(mercado resolve YES). `result` é o resultado DO TRADE.
    Emparelhar os dois direto inverte o sinal em todo trade NO — 93 dos 128
    trades fechados do histórico, 73%. Era a origem do ECE de 0.894 e do
    alerta "Calibração ruim (10.63%)" que derrubaram o health score para 55
    (RED) e cortaram o kelly_factor a 0.2. Com o sinal correto, o Brier do
    mesmo histórico é 0.1043 contra 0.2205 de uma taxa constante.

    Só entram trades que têm `model_prob`; os pares ficam alinhados por
    construção (antes, probabilities() e outcomes() tinham comprimentos
    diferentes quando faltava model_prob, e zip() truncava silenciosamente
    emparelhando trades errados).
    """
    out = []
    for t in _resolved(ds):
        p = t.get("model_prob")
        if p is None:
            p = t.get("probability") or t.get("prob") or t.get("prediction")
        if p is None:
            continue
        try:
            p = float(p)
        except (TypeError, ValueError):
            continue
        side = str(t.get("side") or "YES").upper()
        p_side = p if side == "YES" else 1.0 - p
        out.append((p_side, 1.0 if t.get("result") == "WIN" else 0.0))
    return out


def probabilities(ds):
    return [p for p, _ in _pairs(ds)]

def outcomes(ds):
    return [y for _, y in _pairs(ds)]

def brier_score(ds):
    p=probabilities(ds); y=outcomes(ds)
    return 0.0 if not p else sum((a-b)**2 for a,b in zip(p,y))/len(p)

def log_loss(ds):
    p=probabilities(ds); y=outcomes(ds)
    if not p: return 0.0
    eps=1e-15; s=0.0
    for pr,yy in zip(p,y):
        pr=max(eps,min(1-eps,pr))
        s+=yy*math.log(pr)+(1-yy)*math.log(1-pr)
    return -s/len(p)

def calibration_curve(ds,bins=10):
    b=defaultdict(list)
    for pr,yy in zip(probabilities(ds),outcomes(ds)):
        b[min(int(pr*bins),bins-1)].append((pr,yy))
    out=[]
    for i in range(bins):
        if not b[i]: continue
        out.append({"bin":i,"predicted":mean(v[0] for v in b[i]),"observed":mean(v[1] for v in b[i]),"samples":len(b[i])})
    return out

def expected_calibration_error(ds,bins=10):
    c=calibration_curve(ds,bins); tot=sum(x["samples"] for x in c)
    if tot==0:return 0.0
    return sum(abs(x["predicted"]-x["observed"])*x["samples"]/tot for x in c)

def sharpness(ds):
    p=probabilities(ds)
    return 0.0 if not p else mean(abs(x-0.5) for x in p)

def entropy(ds):
    p=probabilities(ds)
    if not p:return 0.0
    e=[]; eps=1e-15
    for x in p:
        x=max(eps,min(1-eps,x)); e.append(-(x*math.log2(x)+(1-x)*math.log2(1-x)))
    return mean(e)

def prediction_bias(ds):
    p=probabilities(ds); y=outcomes(ds)
    return 0.0 if not p else mean(a-b for a,b in zip(p,y))

def average_confidence(ds):
    p=probabilities(ds)
    return 0.0 if not p else mean(max(x,1-x) for x in p)

def calibration_quality(ds):
    return max(0.0,1.0-expected_calibration_error(ds))

def summary(ds:TradeDataset):
    return {"samples":len(_resolved(ds)),"brier":brier_score(ds),"log_loss":log_loss(ds),"ece":expected_calibration_error(ds),"calibration_quality":calibration_quality(ds),"sharpness":sharpness(ds),"entropy":entropy(ds),"bias":prediction_bias(ds),"confidence":average_confidence(ds),"calibration":calibration_curve(ds)}
