"""Fluxo de potência AC independente do simulador dinâmico."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


class DependenciaOpcionalAusente(RuntimeError):
    """Indica que uma análise elétrica requer uma dependência não instalada."""


def _importar_pandapower() -> Any:
    try:
        import pandapower as pp
    except ImportError as exc:  # pragma: no cover - depende do ambiente
        raise DependenciaOpcionalAusente(
            "A análise elétrica requer 'pandapower'. Instale requirements.txt."
        ) from exc
    return pp


@dataclass(frozen=True)
class ResultadoFluxoPotencia:
    convergiu: bool
    tensoes_pu: dict[str, float]
    carregamento_linhas_percentual: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "analise": "fluxo_potencia",
            "convergiu": self.convergiu,
            "tensoes_pu": self.tensoes_pu,
            "carregamento_linhas_percentual": self.carregamento_linhas_percentual,
        }


class AnaliseFluxoPotencia:
    """Executa fluxo AC em uma rede pandapower fornecida ou de demonstração."""

    # O JSON legado descreve os equipamentos e as conexões, mas não traz
    # parâmetros de impedância dos alimentadores. Esses valores reproduzem a
    # aproximação usada pelo módulo antigo e ficam centralizados para serem
    # substituídos quando o caso elétrico aprovado fornecer esses dados.
    PARAMETROS_LINHA_ENTRADA = {
        "length_km": 0.1,
        "r_ohm_per_km": 0.2,
        "x_ohm_per_km": 0.08,
        "c_nf_per_km": 10.0,
        "max_i_ka": 0.4,
    }

    @staticmethod
    def criar_rede_demo() -> Any:
        pp = _importar_pandapower()
        net = pp.create_empty_network(sn_mva=10.0)
        barra_rede = pp.create_bus(net, vn_kv=13.8, name="Rede")
        barra_carga = pp.create_bus(net, vn_kv=13.8, name="PCC")
        pp.create_ext_grid(
            net,
            barra_rede,
            vm_pu=1.0,
            name="Distribuidora",
            s_sc_max_mva=500.0,
            s_sc_min_mva=300.0,
            rx_max=0.1,
            rx_min=0.1,
            r0x0_max=0.1,
            x0x_max=1.0,
        )
        pp.create_line_from_parameters(
            net,
            barra_rede,
            barra_carga,
            length_km=1.0,
            r_ohm_per_km=0.12,
            x_ohm_per_km=0.18,
            c_nf_per_km=10.0,
            max_i_ka=0.4,
            r0_ohm_per_km=0.36,
            x0_ohm_per_km=0.54,
            c0_nf_per_km=10.0,
            name="Alimentador demo",
        )
        pp.create_load(net, barra_carga, p_mw=0.5, q_mvar=0.164, name="Carga demo")
        return net

    def executar(self, net: Any) -> dict[str, Any]:
        pp = _importar_pandapower()
        pp.runpp(net, algorithm="nr", calculate_voltage_angles=False, numba=False)
        resultado = ResultadoFluxoPotencia(
            convergiu=bool(getattr(net, "converged", False)),
            tensoes_pu={str(index): float(value) for index, value in net.res_bus.vm_pu.items()},
            carregamento_linhas_percentual={
                str(index): float(value)
                for index, value in net.res_line.loading_percent.items()
            }
            if hasattr(net, "res_line")
            else {},
        )
        return resultado.to_dict()

    def executar_arquivo(self, entrada: str | Path) -> dict[str, Any]:
        """Carrega um ``Entradas.json`` próprio e executa o fluxo permanente.

        O formato aceito é o mesmo contrato de equipamentos usado pelo
        simulador transitório e pelo arquivo legado: ``painel_info``,
        ``inversor_info``, ``cargas_info``, ``bateria_info``,
        ``barramento_info``, ``geradordiesel_info`` e ``grafo_conexoes``.
        Cada chamada carrega uma rede nova, sem compartilhar estado com outro
        estudo.
        """
        caminho = Path(entrada).expanduser().resolve()
        net, metadados = self.criar_rede_entrada(caminho)
        resultado = self.executar(net)
        resultado.update(metadados)
        return resultado

    @classmethod
    def criar_rede_entrada(cls, entrada: str | Path) -> tuple[Any, dict[str, Any]]:
        """Constrói uma rede pandapower a partir de um arquivo JSON de entrada."""
        pp = _importar_pandapower()
        caminho = Path(entrada).expanduser().resolve()
        if not caminho.is_file():
            raise FileNotFoundError(f"Arquivo de entrada não encontrado: {caminho}")

        try:
            documento = json.loads(caminho.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON de entrada inválido: {caminho}") from exc
        if not isinstance(documento, dict):
            raise ValueError("O arquivo de entrada deve conter um objeto JSON")

        barramento = cls._primeiro_registro(documento, "barramento_info")
        tensao_linha_v = cls._numero(
            barramento.get("V_linha_nominal"),
            "V_linha_nominal",
            padrao=None,
        )
        if tensao_linha_v is None or tensao_linha_v <= 0:
            inversor = cls._primeiro_registro(documento, "inversor_info")
            tensao_linha_v = cls._numero(inversor.get("Out_VL_nom"), "Out_VL_nom", padrao=13800.0)
        vn_kv = tensao_linha_v / 1000.0

        carga = cls._primeiro_registro(documento, "cargas_info")
        painel = cls._primeiro_registro(documento, "painel_info")
        bateria = cls._primeiro_registro(documento, "bateria_info")
        diesel = cls._primeiro_registro(documento, "geradordiesel_info")
        ids = cls._ids_eletricos(documento, barramento, painel, bateria, carga, diesel)
        sn_mva = max(cls._potencia_aparente_carga_mva(carga), 1.0)
        net = pp.create_empty_network(sn_mva=sn_mva)

        nomes_barras: dict[str, int] = {}
        for identificador in ids:
            nomes_barras[identificador] = pp.create_bus(net, vn_kv=vn_kv, name=identificador)

        bus_principal_id = str(barramento.get("bus_id") or "Bus_ac_1")
        bus_principal = nomes_barras[bus_principal_id]
        conectado_rede = bool(documento.get("conectado_rede", True))
        if conectado_rede:
            barra_rede = pp.create_bus(net, vn_kv=vn_kv, name="Distribuidora")
            pp.create_ext_grid(
                net,
                barra_rede,
                vm_pu=1.0,
                name="Distribuidora",
                s_sc_max_mva=max(sn_mva * 10.0, 1.0),
                s_sc_min_mva=max(sn_mva * 6.0, 0.8),
                rx_max=0.1,
                rx_min=0.1,
                r0x0_max=0.1,
                x0x_max=1.0,
            )
            cls._criar_linha(pp, net, barra_rede, bus_principal, "Alimentador da distribuidora")

        cls._criar_linhas_do_grafo(pp, net, documento.get("grafo_conexoes", []), nomes_barras)

        carga_bus = nomes_barras.get(str(carga.get("carga_id")), bus_principal)
        p_carga_mw, q_carga_mvar = cls._potencia_carga(carga)
        pp.create_load(
            net,
            carga_bus,
            p_mw=p_carga_mw,
            q_mvar=q_carga_mvar,
            name=str(carga.get("nome_carga") or carga.get("carga_id") or "Carga"),
        )

        cls._criar_pv(pp, net, nomes_barras, painel, documento)
        cls._criar_bateria(pp, net, nomes_barras, bateria)

        if not conectado_rede:
            diesel_bus = nomes_barras.get(str(diesel.get("diesel_id")), bus_principal)
            potencia_diesel_kw = cls._numero(diesel.get("potencia_nominal_kw"), "potencia_nominal_kw", 0.0) or 0.0
            if potencia_diesel_kw <= 0:
                raise ValueError(
                    "A entrada está ilhada (conectado_rede=false) e não possui "
                    "gerador diesel com potência nominal para servir de referência."
                )
            if diesel_bus != bus_principal and not cls._existe_ligacao(net, diesel_bus, bus_principal):
                cls._criar_linha(pp, net, bus_principal, diesel_bus, "Conexão do gerador diesel")
            parametros_diesel = cls._parametros_diesel_pandapower(diesel, potencia_diesel_kw, vn_kv)
            pp.create_gen(
                net,
                diesel_bus,
                p_mw=parametros_diesel["p_mw_inicial"],
                vm_pu=1.0,
                slack=True,
                name=str(diesel.get("diesel_id") or "Gerador diesel"),
                sn_mva=parametros_diesel["sn_mva"],
                max_p_mw=parametros_diesel["max_p_mw"],
                min_p_mw=parametros_diesel["min_p_mw"],
                type="sync",
                vn_kv=parametros_diesel["vn_kv"],
                xdss_pu=parametros_diesel["xdss_pu"],
                rdss_ohm=parametros_diesel["rdss_ohm"],
                cos_phi=parametros_diesel["cos_phi"],
            )
        elif diesel:
            diesel_bus = nomes_barras.get(str(diesel.get("diesel_id")), bus_principal)
            potencia_diesel_kw = cls._numero(diesel.get("potencia_nominal_kw"), "potencia_nominal_kw", 0.0) or 0.0
            parametros_diesel = cls._parametros_diesel_pandapower(diesel, potencia_diesel_kw, vn_kv)
            pp.create_gen(
                net,
                diesel_bus,
                p_mw=0.0,
                vm_pu=1.0,
                slack=False,
                name=str(diesel.get("diesel_id") or "Gerador diesel"),
                sn_mva=parametros_diesel["sn_mva"],
                max_p_mw=parametros_diesel["max_p_mw"],
                min_p_mw=parametros_diesel["min_p_mw"],
                type="sync",
                vn_kv=parametros_diesel["vn_kv"],
                xdss_pu=parametros_diesel["xdss_pu"],
                rdss_ohm=parametros_diesel["rdss_ohm"],
                cos_phi=parametros_diesel["cos_phi"],
            )

        return net, {
            "arquivo_entrada": str(caminho),
            "nome_projeto": documento.get("nome_projeto"),
            "modelo_rede": "entradas_json",
            "conectado_rede": conectado_rede,
            "parametros_linha_padrao": dict(cls.PARAMETROS_LINHA_ENTRADA),
            "parametros_gerador_diesel_pandapower": (
                cls._parametros_diesel_pandapower(diesel, cls._numero(diesel.get("potencia_nominal_kw"), "potencia_nominal_kw", 0.0) or 0.0, vn_kv)
                if diesel
                else None
            ),
        }

    @staticmethod
    def _primeiro_registro(documento: dict[str, Any], chave: str) -> dict[str, Any]:
        registros = documento.get(chave, [])
        if registros is None:
            return {}
        if not isinstance(registros, list):
            raise ValueError(f"{chave} deve ser uma lista de registros")
        if not registros:
            return {}
        if not isinstance(registros[0], dict):
            raise ValueError(f"{chave}[0] deve ser um objeto")
        return registros[0]

    @staticmethod
    def _numero(valor: Any, nome: str, padrao: float | None) -> float | None:
        if valor is None or valor == "":
            return padrao
        try:
            numero = float(valor)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{nome} deve ser numérico") from exc
        return numero

    @classmethod
    def _quantidade(cls, valor: Any) -> int:
        valores = valor if isinstance(valor, list) else [valor]
        total = 1
        for item in valores:
            numero = cls._numero(item, "quantidade", 1.0) or 1.0
            total *= max(int(numero), 1)
        return total

    @classmethod
    def _ids_eletricos(
        cls,
        documento: dict[str, Any],
        barramento: dict[str, Any],
        painel: dict[str, Any],
        bateria: dict[str, Any],
        carga: dict[str, Any],
        diesel: dict[str, Any],
    ) -> list[str]:
        ids = [str(barramento.get("bus_id") or "Bus_ac_1")]
        for registro, campo in (
            (painel, "pv_id"),
            (documento.get("inversor_info", [{}])[0] if documento.get("inversor_info") else {}, "inv_id"),
            (bateria, "bateria_id"),
            (carga, "carga_id"),
            (diesel, "diesel_id"),
        ):
            identificador = registro.get(campo)
            if identificador:
                ids.append(str(identificador))
        resultado: list[str] = []
        for identificador in ids:
            if identificador not in resultado:
                resultado.append(identificador)
        return resultado

    @classmethod
    def _potencia_aparente_carga_mva(cls, carga: dict[str, Any]) -> float:
        # O contrato legado informa s_instalada em VA (ex.: 12000 = 12 kVA).
        s_kva = (cls._numero(carga.get("s_instalada"), "s_instalada", 0.0) or 0.0) / 1000.0
        return s_kva * cls._quantidade(carga.get("quantidade", 1)) / 1000.0

    @classmethod
    def _potencia_carga(cls, carga: dict[str, Any]) -> tuple[float, float]:
        quantidade = cls._quantidade(carga.get("quantidade", 1))
        # O contrato legado informa s_instalada em VA (ex.: 12000 = 12 kVA).
        s_kva = (cls._numero(carga.get("s_instalada"), "s_instalada", 0.0) or 0.0) / 1000.0
        potencia_kw = cls._numero(carga.get("potencia_kw"), "potencia_kw", None)
        if potencia_kw is None:
            fp = cls._numero(carga.get("fp"), "fp", 1.0) or 1.0
            if not 0 < fp <= 1:
                raise ValueError("fp da carga deve estar entre zero e um")
            potencia_kw = s_kva * fp
        potencia_kw *= quantidade
        fp = cls._numero(carga.get("fp"), "fp", 1.0) or 1.0
        q_kvar = potencia_kw * ((1.0 - fp**2) ** 0.5) / fp if fp < 1 else 0.0
        return potencia_kw / 1000.0, q_kvar / 1000.0

    @classmethod
    def _parametros_diesel_pandapower(
        cls,
        diesel: dict[str, Any],
        potencia_nominal_kw: float,
        vn_rede_kv: float,
    ) -> dict[str, float]:
        """Converte o contrato do diesel para os campos do elemento ``gen``.

        O arquivo legado informa a tensão em volts e a potência em kW. O
        elemento síncrono do pandapower usa kV, MW e a potência aparente da
        máquina, além de ``xdss_pu``/``rdss_ohm`` para curto-circuito.
        Defaults conservadores mantêm a compatibilidade com entradas antigas
        que ainda não possuíam os dados de impedância.
        """

        fator_potencia = cls._numero(diesel.get("fator_potencia"), "fator_potencia", 0.8) or 0.8
        if not 0 < fator_potencia <= 1:
            raise ValueError("fator_potencia do gerador diesel deve estar entre zero e um")
        tensao_kv = cls._numero(diesel.get("tensao_nominal_kv"), "tensao_nominal_kv", None)
        if tensao_kv is None:
            tensao_v = cls._numero(diesel.get("tensao_nominal"), "tensao_nominal", None)
            tensao_kv = tensao_v / 1000.0 if tensao_v is not None else vn_rede_kv
        if tensao_kv <= 0:
            raise ValueError("tensao nominal do gerador diesel deve ser positiva")
        potencia_maxima_kw = cls._numero(
            diesel.get("potencia_maxima_kw"),
            "potencia_maxima_kw",
            potencia_nominal_kw,
        ) or potencia_nominal_kw
        potencia_minima_kw = cls._numero(
            diesel.get("potencia_minima_kw"),
            "potencia_minima_kw",
            0.0,
        ) or 0.0
        xdss_pu = cls._numero(diesel.get("xdss_pu"), "xdss_pu", 0.2) or 0.2
        rdss_ohm = cls._numero(diesel.get("rdss_ohm"), "rdss_ohm", 0.01) or 0.01
        if potencia_nominal_kw <= 0 or potencia_maxima_kw <= 0:
            raise ValueError("potência nominal/máxima do gerador diesel deve ser positiva")
        if not 0 <= potencia_minima_kw <= potencia_maxima_kw:
            raise ValueError("potência mínima do gerador diesel deve atender min <= max")
        if xdss_pu <= 0 or rdss_ohm < 0:
            raise ValueError("xdss_pu deve ser positivo e rdss_ohm não pode ser negativo")
        sn_mva = max(potencia_nominal_kw / 1000.0 / fator_potencia, 0.1)
        return {
            "p_mw_inicial": potencia_nominal_kw / 1000.0,
            "sn_mva": sn_mva,
            "max_p_mw": potencia_maxima_kw / 1000.0,
            "min_p_mw": potencia_minima_kw / 1000.0,
            "vn_kv": tensao_kv,
            "xdss_pu": xdss_pu,
            "rdss_ohm": rdss_ohm,
            "cos_phi": fator_potencia,
        }

    @classmethod
    def _criar_pv(
        cls,
        pp: Any,
        net: Any,
        nomes_barras: dict[str, int],
        painel: dict[str, Any],
        documento: dict[str, Any],
    ) -> None:
        if not painel:
            return
        potencia_kw = (cls._numero(painel.get("Pmp"), "Pmp", 0.0) or 0.0) * cls._quantidade(painel.get("quantidade", 1)) / 1000.0
        inversor = cls._primeiro_registro(documento, "inversor_info")
        potencia_max_kw = cls._numero(inversor.get("Out_Pmax"), "Out_Pmax", None)
        if potencia_max_kw is not None and potencia_max_kw > 0:
            potencia_kw = min(potencia_kw, potencia_max_kw * cls._quantidade(inversor.get("quantidade", 1)))
        if potencia_kw <= 0:
            return
        barra = nomes_barras.get(str(painel.get("pv_id")), next(iter(nomes_barras.values())))
        eficiencia = cls._numero(inversor.get("Eficiencia"), "Eficiencia", 1.0) or 1.0
        potencia_sgen_mw = potencia_kw * eficiencia / 1000.0
        pp.create_sgen(
            net,
            barra,
            p_mw=potencia_sgen_mw,
            q_mvar=0.0,
            sn_mva=max(potencia_sgen_mw, 0.1),
            k=1.2,
            name=str(painel.get("pv_id") or "FV"),
        )

    @classmethod
    def _criar_bateria(cls, pp: Any, net: Any, nomes_barras: dict[str, int], bateria: dict[str, Any]) -> None:
        if not bateria:
            return
        barra = nomes_barras.get(str(bateria.get("bateria_id")), next(iter(nomes_barras.values())))
        potencia_bess_kw = max(
            cls._numero(bateria.get("potencia_max_carga_kw"), "potencia_max_carga_kw", 0.0) or 0.0,
            cls._numero(bateria.get("potencia_max_descarga_kw"), "potencia_max_descarga_kw", 0.0) or 0.0,
            100.0,
        )
        pp.create_sgen(
            net,
            barra,
            p_mw=0.0,
            q_mvar=0.0,
            sn_mva=potencia_bess_kw / 1000.0,
            k=1.2,
            name=str(bateria.get("bateria_id") or "BESS"),
        )

    @classmethod
    def _criar_linhas_do_grafo(cls, pp: Any, net: Any, grafo: Any, nomes_barras: dict[str, int]) -> None:
        if grafo is None:
            return
        if not isinstance(grafo, list):
            raise ValueError("grafo_conexoes deve ser uma lista")
        for item in grafo:
            if not isinstance(item, dict):
                continue
            extremos = item.get("between")
            if not isinstance(extremos, list) or len(extremos) != 2:
                continue
            origem, destino = (str(extremos[0]), str(extremos[1]))
            if origem not in nomes_barras or destino not in nomes_barras:
                continue
            origem_bus, destino_bus = nomes_barras[origem], nomes_barras[destino]
            if origem_bus == destino_bus or cls._existe_ligacao(net, origem_bus, destino_bus):
                continue
            cls._criar_linha(pp, net, origem_bus, destino_bus, f"{origem}-{destino}")

    @classmethod
    def _criar_linha(cls, pp: Any, net: Any, origem: int, destino: int, nome: str) -> None:
        pp.create_line_from_parameters(net, origem, destino, name=nome, **cls.PARAMETROS_LINHA_ENTRADA)

    @staticmethod
    def _existe_ligacao(net: Any, origem: int, destino: int) -> bool:
        if not hasattr(net, "line") or net.line.empty:
            return False
        pares = {(int(row.from_bus), int(row.to_bus)) for row in net.line.itertuples()}
        return (origem, destino) in pares or (destino, origem) in pares

    def executar_demo(self) -> dict[str, Any]:
        return self.executar(self.criar_rede_demo())
