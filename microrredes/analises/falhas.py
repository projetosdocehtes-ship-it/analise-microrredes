"""Análise de curto-circuito desacoplada do fluxo de potência."""

from __future__ import annotations

from typing import Any

from .fluxo_potencia import AnaliseFluxoPotencia, DependenciaOpcionalAusente, _importar_pandapower


class AnaliseFalhas:
    """Calcula correntes de curto-circuito usando a rede elétrica já modelada."""

    def executar(
        self,
        net: Any,
        tipo: str = "3ph",
        caso: str = "max",
        impedancia_falha_ohm: float = 0.0,
    ) -> dict[str, Any]:
        if tipo not in {"3ph", "2ph", "1ph"}:
            raise ValueError("tipo deve ser '3ph', '2ph' ou '1ph'")
        if caso not in {"max", "min"}:
            raise ValueError("caso deve ser 'max' ou 'min'")
        if impedancia_falha_ohm < 0:
            raise ValueError("A impedância da falha não pode ser negativa")

        pp = _importar_pandapower()
        from pandapower.shortcircuit import calc_sc

        calc_sc(
            net,
            fault=tipo,
            case=caso,
            r_fault_ohm=impedancia_falha_ohm,
            x_fault_ohm=0.0,
            branch_results=True,
        )

        correntes = {
            str(index): float(value)
            for index, value in net.res_bus_sc.ikss_ka.items()
        }
        return {
            "analise": "curto_circuito",
            "tipo": tipo,
            "caso": caso,
            "impedancia_falha_ohm": impedancia_falha_ohm,
            "corrente_inicial_simetrica_ka": correntes,
            "barras_avaliadas": len(correntes),
        }

    def executar_demo(self, tipo: str = "3ph", caso: str = "max") -> dict[str, Any]:
        return self.executar(AnaliseFluxoPotencia.criar_rede_demo(), tipo=tipo, caso=caso)


__all__ = ["AnaliseFalhas", "DependenciaOpcionalAusente"]
