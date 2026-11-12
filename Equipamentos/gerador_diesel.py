"""Componente dinâmico reduzido de gerador síncrono a diesel.

As equações são mantidas no componente para que ele possa ser reutilizado por
um simulador de equipamento, por um cenário transitório e, futuramente, pelo
adaptador do arquivo ``Entradas.Json``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any


@dataclass(frozen=True)
class ParametrosGeradorDiesel:
    """Parâmetros elétricos, mecânicos e de controle do grupo."""

    id_gerador: str = "Diesel_1"
    potencia_nominal_kw: float = 275.0
    potencia_minima_kw: float = 82.5
    potencia_maxima_kw: float | None = None
    potencia_inicial_kw: float | None = None
    tensao_nominal_kv: float = 0.38
    frequencia_nominal_hz: float = 60.0
    fator_potencia: float = 0.8
    inercia_s: float = 2.5
    droop_percent: float = 4.0
    tempo_governador_s: float = 0.20
    tempo_motor_s: float = 0.50
    tempo_avr_s: float = 0.05
    ganho_avr: float = 20.0
    tensao_referencia_pu: float = 1.0
    tensao_minima_pu: float = 0.70
    tensao_maxima_pu: float = 1.10
    queda_tensao_carga_pu: float = 0.04
    amortecimento_frequencia: float = 0.05
    xdss_pu: float = 0.20
    xd_pu: float = 0.35
    rdss_ohm: float = 0.01
    constante_decaimento_curto_s: float = 0.15

    def __post_init__(self) -> None:
        potencia_maxima = self.potencia_maxima_kw
        if potencia_maxima is None:
            object.__setattr__(self, "potencia_maxima_kw", self.potencia_nominal_kw)
            potencia_maxima = self.potencia_nominal_kw
        if self.potencia_nominal_kw <= 0:
            raise ValueError("potencia_nominal_kw deve ser positiva")
        if not 0 <= self.potencia_minima_kw <= potencia_maxima <= self.potencia_nominal_kw:
            raise ValueError("A faixa de potência deve atender min <= max <= nominal")
        if self.potencia_inicial_kw is not None and not 0 <= self.potencia_inicial_kw <= potencia_maxima:
            raise ValueError("potencia_inicial_kw deve estar entre zero e potencia_maxima_kw")
        if self.tensao_nominal_kv <= 0 or self.frequencia_nominal_hz <= 0:
            raise ValueError("tensao_nominal_kv e frequencia_nominal_hz devem ser positivas")
        if not 0 < self.fator_potencia <= 1:
            raise ValueError("fator_potencia deve estar entre zero e um")
        if self.inercia_s <= 0 or self.droop_percent <= 0:
            raise ValueError("inercia_s e droop_percent devem ser positivos")
        if min(self.tempo_governador_s, self.tempo_motor_s, self.tempo_avr_s) <= 0:
            raise ValueError("As constantes de tempo devem ser positivas")
        if self.ganho_avr <= 0:
            raise ValueError("ganho_avr deve ser positivo")
        if not 0 < self.tensao_minima_pu < self.tensao_maxima_pu:
            raise ValueError("Os limites de tensão devem atender minimo < maximo")
        if not self.tensao_minima_pu <= self.tensao_referencia_pu <= self.tensao_maxima_pu:
            raise ValueError("tensao_referencia_pu deve estar entre os limites")
        if self.xdss_pu <= 0 or self.xd_pu <= 0 or self.rdss_ohm < 0:
            raise ValueError("xdss_pu, xd_pu e rdss_ohm devem ser válidos")
        if self.xdss_pu > self.xd_pu:
            raise ValueError("xdss_pu não pode ser maior que xd_pu")
        if self.constante_decaimento_curto_s <= 0:
            raise ValueError("constante_decaimento_curto_s deve ser positiva")


@dataclass
class EstadoGeradorDiesel:
    """Estado diferencial do grupo em um instante de simulação."""

    frequencia_hz: float
    angulo_rotor_rad: float
    potencia_governador_kw: float
    potencia_mecanica_kw: float
    tensao_pu: float


class GeradorDiesel:
    r"""Modelo de primeira ordem com governador, motor, rotor e AVR.

    Para ``P_g`` ser a saída do governador, ``P_m`` a potência mecânica,
    ``P_e`` a potência elétrica, ``f`` a frequência e ``V`` a tensão:

    .. math::

       \dot P_g = (P_{cmd} - P_g) / T_g
       \dot P_m = (P_g - P_m) / T_m
       \dot f = f_n (P_m-P_e)/(2H P_n) - D(f-f_n)
       \dot \delta = 2\pi(f-f_n)
       \dot V = (V_{cmd}-V)/T_{AVR}

    O governador usa a característica de droop:

    .. math::

       P_{cmd} = sat(P_{ref} + P_n(f_n-f)/(R f_n))

    ``passo`` usa Euler explícito para manter o mesmo contrato simples dos
    componentes legados. O passo deve ser escolhido menor que as constantes
    de tempo do modelo.
    """

    def __init__(self, parametros: ParametrosGeradorDiesel | None = None):
        self.parametros = parametros or ParametrosGeradorDiesel()
        self.estado = EstadoGeradorDiesel(
            frequencia_hz=self.parametros.frequencia_nominal_hz,
            angulo_rotor_rad=0.0,
            potencia_governador_kw=0.0,
            potencia_mecanica_kw=0.0,
            tensao_pu=self.parametros.tensao_referencia_pu,
        )
        self.historico: list[EstadoGeradorDiesel] = []

    def inicializar(self, carga_inicial_kw: float = 0.0) -> EstadoGeradorDiesel:
        p_max = self.parametros.potencia_maxima_kw or self.parametros.potencia_nominal_kw
        potencia = self.parametros.potencia_inicial_kw
        if potencia is None:
            potencia = _limitar(carga_inicial_kw, self.parametros.potencia_minima_kw, p_max)
        self.estado = EstadoGeradorDiesel(
            frequencia_hz=self.parametros.frequencia_nominal_hz,
            angulo_rotor_rad=0.0,
            potencia_governador_kw=potencia,
            potencia_mecanica_kw=potencia,
            tensao_pu=self.parametros.tensao_referencia_pu,
        )
        self.historico = []
        return self.estado

    def comando_governador(self, potencia_referencia_kw: float | None = None) -> float:
        p_ref = self.estado.potencia_mecanica_kw if potencia_referencia_kw is None else potencia_referencia_kw
        ganho_kw_por_hz = self.parametros.potencia_nominal_kw / (
            self.parametros.droop_percent / 100.0 * self.parametros.frequencia_nominal_hz
        )
        comando = p_ref + ganho_kw_por_hz * (
            self.parametros.frequencia_nominal_hz - self.estado.frequencia_hz
        )
        return _limitar(
            comando,
            self.parametros.potencia_minima_kw,
            self.parametros.potencia_maxima_kw or self.parametros.potencia_nominal_kw,
        )

    def equacoes_diferenciais(
        self,
        potencia_eletrica_kw: float,
        tensao_comando_pu: float,
        potencia_referencia_kw: float | None = None,
    ) -> dict[str, float]:
        """Retorna as derivadas do estado sem alterar o componente."""

        p_cmd = self.comando_governador(potencia_referencia_kw)
        p_base = self.parametros.potencia_nominal_kw
        f_nom = self.parametros.frequencia_nominal_hz
        d_frequencia = f_nom * (
            (self.estado.potencia_mecanica_kw - potencia_eletrica_kw) / p_base
        ) / (2.0 * self.parametros.inercia_s)
        d_frequencia -= self.parametros.amortecimento_frequencia * (
            self.estado.frequencia_hz - f_nom
        )
        return {
            "potencia_comando_kw": p_cmd,
            "d_potencia_governador_dt_kw_s": (
                p_cmd - self.estado.potencia_governador_kw
            ) / self.parametros.tempo_governador_s,
            "d_potencia_mecanica_dt_kw_s": (
                self.estado.potencia_governador_kw - self.estado.potencia_mecanica_kw
            ) / self.parametros.tempo_motor_s,
            "d_frequencia_dt_hz_s": d_frequencia,
            "d_angulo_rotor_dt_rad_s": 2.0 * math.pi * (
                self.estado.frequencia_hz - f_nom
            ),
            "d_tensao_dt_pu_s": (
                tensao_comando_pu - self.estado.tensao_pu
            ) / self.parametros.tempo_avr_s,
        }

    def passo(
        self,
        passo_s: float,
        potencia_eletrica_kw: float,
        tensao_comando_pu: float,
        potencia_referencia_kw: float | None = None,
    ) -> EstadoGeradorDiesel:
        """Integra uma amostra do estado por Euler explícito."""

        if passo_s <= 0:
            raise ValueError("passo_s deve ser positivo")
        derivadas = self.equacoes_diferenciais(
            potencia_eletrica_kw,
            tensao_comando_pu,
            potencia_referencia_kw,
        )
        p_max = self.parametros.potencia_maxima_kw or self.parametros.potencia_nominal_kw
        self.estado.potencia_governador_kw = _limitar(
            self.estado.potencia_governador_kw
            + passo_s * derivadas["d_potencia_governador_dt_kw_s"],
            self.parametros.potencia_minima_kw,
            p_max,
        )
        self.estado.potencia_mecanica_kw = _limitar(
            self.estado.potencia_mecanica_kw
            + passo_s * derivadas["d_potencia_mecanica_dt_kw_s"],
            0.0,
            p_max,
        )
        self.estado.frequencia_hz = max(
            self.estado.frequencia_hz + passo_s * derivadas["d_frequencia_dt_hz_s"],
            0.1,
        )
        self.estado.angulo_rotor_rad += passo_s * derivadas["d_angulo_rotor_dt_rad_s"]
        self.estado.tensao_pu = _limitar(
            self.estado.tensao_pu + passo_s * derivadas["d_tensao_dt_pu_s"],
            self.parametros.tensao_minima_pu,
            self.parametros.tensao_maxima_pu,
        )
        self.historico.append(EstadoGeradorDiesel(**asdict(self.estado)))
        return self.estado

    def corrente_curto_transitoria(
        self,
        corrente_ikss_rede_ka: float,
        tempo_curto_s: float,
        resistencia_falta_ohm: float = 0.0,
        reatancia_falta_ohm: float = 0.0,
        comprimento_linha_km: float = 0.0,
        resistencia_linha_ohm_km: float = 0.0,
        reatancia_linha_ohm_km: float = 0.0,
    ) -> float:
        """Aproxima o decaimento de :math:`I''_k` durante uma falta trifásica."""

        p = self.parametros
        z_base_ohm = p.tensao_nominal_kv**2 / (p.potencia_nominal_kw / 1000.0 / p.fator_potencia)
        z_linha = complex(
            comprimento_linha_km * resistencia_linha_ohm_km,
            comprimento_linha_km * reatancia_linha_ohm_km,
        )
        z_falta = complex(resistencia_falta_ohm, reatancia_falta_ohm)
        z_subtransitoria = complex(p.rdss_ohm, p.xdss_pu * z_base_ohm)
        modulo_impedancia = abs(z_subtransitoria + z_linha + z_falta)
        if modulo_impedancia <= 0:
            return corrente_ikss_rede_ka
        corrente_falta_ka = p.tensao_nominal_kv / (math.sqrt(3.0) * modulo_impedancia)
        corrente_regime_ka = corrente_falta_ka * p.xdss_pu / p.xd_pu
        return corrente_regime_ka + (corrente_falta_ka - corrente_regime_ka) * math.exp(
            -max(tempo_curto_s, 0.0) / p.constante_decaimento_curto_s
        )

    def exportar_estado(self) -> dict[str, Any]:
        return {
            "parametros": asdict(self.parametros),
            "estado": asdict(self.estado),
            "historico": [asdict(item) for item in self.historico],
        }


def _limitar(valor: float, minimo: float, maximo: float) -> float:
    return min(max(float(valor), float(minimo)), float(maximo))


__all__ = ["EstadoGeradorDiesel", "GeradorDiesel", "ParametrosGeradorDiesel"]
