"""Cliente da fonte oficial de tarifas de aplicação da ANEEL.

O módulo consulta o endpoint CKAN do Portal de Dados Abertos da ANEEL,
seleciona a vigência mais recente aplicável e normaliza TE/TUSD para R$/kWh
(consumo) e R$/kW (demanda). O fallback local é deliberadamente opt-in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import csv
import io
import json
from pathlib import Path
import unicodedata
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

import requests


def _normalizar(texto: Any) -> str:
    valor = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(char for char in valor if not unicodedata.combining(char)).strip().lower()


def _numero_br(valor: Any) -> float:
    if valor is None or str(valor).strip() == "":
        return 0.0
    texto = str(valor).strip().replace("R$", "").replace(" ", "")
    if "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif "," in texto:
        texto = texto.replace(",", ".")
    try:
        return float(texto)
    except ValueError as exc:
        raise ErroTarifasANEEL(f"Valor tarifário inválido: {valor!r}") from exc


def _data(valor: Any) -> date | None:
    if valor in (None, ""):
        return None
    texto = str(valor).strip()
    try:
        return datetime.fromisoformat(texto.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(texto[:10])
        except ValueError:
            return None


def _valor_tarifario(valor: Any, unidade: Any, energia: bool) -> float:
    bruto = _numero_br(valor)
    unidade_normalizada = _normalizar(unidade).replace(" ", "")
    if energia and "mwh" in unidade_normalizada and "kwh" not in unidade_normalizada:
        return bruto / 1000.0
    # Algumas versões antigas da base não informavam a unidade e traziam
    # consumo em R$/MWh. Mantemos a heurística apenas para esse caso.
    if energia and not unidade_normalizada and abs(bruto) > 10:
        return bruto / 1000.0
    return bruto


class ErroTarifasANEEL(RuntimeError):
    """Erro sanitizado ao consultar ou validar a fonte tarifária."""


@dataclass(frozen=True)
class TarifaSnapshot:
    distribuidora: str
    grupo: str
    vigencia_inicio: date | None
    vigencia_fim: date | None
    fonte: str
    consultado_em_utc: str
    registros_consultados: int
    azul: dict[str, float] = field(default_factory=dict)
    verde: dict[str, float] = field(default_factory=dict)
    modo_acesso: str = "online"
    cache_atualizado_em_utc: str | None = None
    cache_idade_dias: float | None = None
    avisos: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "distribuidora": self.distribuidora,
            "grupo": self.grupo,
            "vigencia_inicio": self.vigencia_inicio.isoformat() if self.vigencia_inicio else None,
            "vigencia_fim": self.vigencia_fim.isoformat() if self.vigencia_fim else None,
            "fonte": self.fonte,
            "consultado_em_utc": self.consultado_em_utc,
            "registros_consultados": self.registros_consultados,
            "azul": dict(self.azul),
            "verde": dict(self.verde),
            "modo_acesso": self.modo_acesso,
            "cache_atualizado_em_utc": self.cache_atualizado_em_utc,
            "cache_idade_dias": self.cache_idade_dias,
            "avisos": list(self.avisos),
        }

    @classmethod
    def de_registros(
        cls,
        registros: Iterable[Mapping[str, Any]],
        distribuidora: str,
        grupo: str,
        fonte: str = "ANEEL",
        consultado_em_utc: str | None = None,
    ) -> "TarifaSnapshot":
        linhas = [dict(registro) for registro in registros]
        if not linhas:
            raise ErroTarifasANEEL("A fonte não retornou registros tarifários")

        valores = {
            "azul": {
                "tusd_ponta_demanda": 0.0,
                "tusd_fora_ponta_demanda": 0.0,
                "tusd_ponta_consumo": 0.0,
                "tusd_fora_ponta_consumo": 0.0,
                "te_ponta": 0.0,
                "te_fora_ponta": 0.0,
            },
            "verde": {
                "tusd_demanda": 0.0,
                "tusd_ponta_consumo": 0.0,
                "tusd_fora_ponta_consumo": 0.0,
                "te_ponta": 0.0,
                "te_fora_ponta": 0.0,
            },
        }
        datas_inicio = [_data(linha.get("DatInicioVigencia")) for linha in linhas]
        datas_fim = [_data(linha.get("DatFimVigencia")) for linha in linhas]

        for linha in linhas:
            modalidade = _normalizar(linha.get("DscModalidadeTarifaria"))
            if modalidade not in {"azul", "verde"}:
                continue
            detalhe = _normalizar(linha.get("DscDetalhe"))
            if "scee" in detalhe:
                continue
            posto = _normalizar(linha.get("NomPostoTarifario"))
            unidade = _normalizar(linha.get("DscUnidadeTerciaria"))
            is_demanda = "kw" in unidade and "kwh" not in unidade
            if not is_demanda and "demanda" in detalhe:
                is_demanda = True

            if modalidade == "azul" and is_demanda:
                chave = "tusd_ponta_demanda" if "ponta" == posto else "tusd_fora_ponta_demanda"
                _preencher(valores["azul"], chave, _valor_tarifario(linha.get("VlrTUSD"), unidade, False))
                continue
            if modalidade == "verde" and is_demanda:
                _preencher(valores["verde"], "tusd_demanda", _valor_tarifario(linha.get("VlrTUSD"), unidade, False))
                continue

            if posto not in {"ponta", "fora ponta"}:
                continue
            sufixo = "ponta" if posto == "ponta" else "fora_ponta"
            destino = valores[modalidade]
            _preencher(
                destino,
                f"tusd_{sufixo}_consumo",
                _valor_tarifario(linha.get("VlrTUSD"), unidade, True),
            )
            _preencher(destino, f"te_{sufixo}", _valor_tarifario(linha.get("VlrTE"), unidade, True))

        return cls(
            distribuidora=str(distribuidora),
            grupo=str(grupo),
            vigencia_inicio=max((item for item in datas_inicio if item is not None), default=None),
            vigencia_fim=max((item for item in datas_fim if item is not None), default=None),
            fonte=fonte,
            consultado_em_utc=consultado_em_utc or datetime.now(timezone.utc).isoformat(),
            registros_consultados=len(linhas),
            azul=valores["azul"],
            verde=valores["verde"],
        )


def _preencher(destino: dict[str, float], chave: str, valor: float) -> None:
    if valor and destino.get(chave, 0.0) == 0.0:
        destino[chave] = float(valor)


class ClienteTarifasANEEL:
    API_BASE_URL = "https://dadosabertos.aneel.gov.br/api/3/action/datastore_search"
    RESOURCE_ID = "fcf2906c-7c32-4b9b-a637-054e7a5234f4"
    CSV_URL = (
        "https://dadosabertos.aneel.gov.br/dataset/5a583f3e-1646-4f67-bf0f-69db4203e89e/"
        "resource/fcf2906c-7c32-4b9b-a637-054e7a5234f4/download/"
        "tarifas-homologadas-distribuidoras-energia-eletrica.csv"
    )
    CACHE_SCHEMA_VERSION = "1.0"
    DEFAULT_CACHE_PATH = Path(__file__).with_name("cache") / "tarifas_aneel_cache.json"

    def __init__(
        self,
        distribuidora: str = "EQUATORIAL GO",
        grupo: str = "A4",
        timeout: float = 30.0,
        permitir_fallback: bool = False,
        session: requests.Session | None = None,
        cache_path: str | Path | None = None,
        cache_ttl_days: float = 7.0,
        usar_cache: bool = True,
        permitir_cache_expirado: bool = True,
        atualizar_cache: bool = True,
    ) -> None:
        self.distribuidora = str(distribuidora).strip().upper()
        self.grupo = str(grupo).strip().upper()
        self.timeout = timeout
        self.permitir_fallback = permitir_fallback
        self.session = session or requests.Session()
        self.cache_path = Path(cache_path) if cache_path else self.DEFAULT_CACHE_PATH
        self.cache_ttl_days = float(cache_ttl_days)
        if self.cache_ttl_days < 0:
            raise ValueError("cache_ttl_days não pode ser negativo")
        self.usar_cache = usar_cache
        self.permitir_cache_expirado = permitir_cache_expirado
        self.atualizar_cache = atualizar_cache
        self._ultima_fonte = "ANEEL_CKAN"

    def carregar(self, referencia: date | None = None) -> TarifaSnapshot:
        data_brasilia = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
        referencia_efetiva = referencia or data_brasilia
        self._referencia_consulta = referencia_efetiva
        try:
            registros = self._buscar_registros()
            selecionados = self._selecionar_vigencia(registros, referencia_efetiva)
            snapshot = TarifaSnapshot.de_registros(
                selecionados,
                distribuidora=self.distribuidora,
                grupo=self.grupo,
                fonte=self._ultima_fonte,
            )
            self._validar_snapshot(snapshot)
            if self.atualizar_cache:
                self._salvar_cache(snapshot, selecionados)
            return snapshot
        except (requests.RequestException, ErroTarifasANEEL, ValueError) as exc:
            if self.usar_cache:
                snapshot_cache = self._carregar_cache()
                if snapshot_cache is not None:
                    self._validar_snapshot(snapshot_cache)
                    return snapshot_cache
            if not self.permitir_fallback:
                if isinstance(exc, ErroTarifasANEEL):
                    raise
                raise ErroTarifasANEEL(f"Não foi possível consultar a ANEEL: {exc}") from exc
            return self._fallback()

    def _cache_chave(self) -> str:
        return f"{_normalizar(self.distribuidora)}|{_normalizar(self.grupo)}"

    def _carregar_cache(self) -> TarifaSnapshot | None:
        if not self.cache_path.exists():
            return None
        try:
            documento = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ErroTarifasANEEL(f"Cache tarifário inválido: {self.cache_path}") from exc

        if documento.get("cache_schema_version") != self.CACHE_SCHEMA_VERSION:
            raise ErroTarifasANEEL("Versão do cache tarifário incompatível")
        entrada = next(
            (item for item in documento.get("entradas", []) if item.get("chave") == self._cache_chave()),
            None,
        )
        if not entrada:
            return None
        dados = entrada.get("snapshot") or {}
        atualizado = entrada.get("atualizado_em_utc") or dados.get("consultado_em_utc")
        if not atualizado:
            raise ErroTarifasANEEL("Cache tarifário sem data de atualização")
        try:
            atualizado_dt = datetime.fromisoformat(str(atualizado).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ErroTarifasANEEL("Cache tarifário com data inválida") from exc
        if atualizado_dt.tzinfo is None:
            atualizado_dt = atualizado_dt.replace(tzinfo=timezone.utc)
        idade_dias = max(0.0, (datetime.now(timezone.utc) - atualizado_dt).total_seconds() / 86400.0)
        expirado = idade_dias > self.cache_ttl_days
        if expirado and not self.permitir_cache_expirado:
            raise ErroTarifasANEEL(
                f"Cache tarifário expirado há {idade_dias:.1f} dias: {self.cache_path}"
            )
        referencia = getattr(self, "_referencia_consulta", None)
        vigencia_inicio = _data(dados.get("vigencia_inicio"))
        vigencia_fim = _data(dados.get("vigencia_fim"))
        if referencia and vigencia_inicio and referencia < vigencia_inicio:
            return None
        if referencia and vigencia_fim and referencia > vigencia_fim:
            return None
        avisos = list(dados.get("avisos") or [])
        if expirado:
            avisos.append(
                f"Cache tarifário expirado há {idade_dias:.1f} dias; conexão ANEEL indisponível."
            )
        return TarifaSnapshot(
            distribuidora=str(dados.get("distribuidora", self.distribuidora)),
            grupo=str(dados.get("grupo", self.grupo)),
            vigencia_inicio=vigencia_inicio,
            vigencia_fim=vigencia_fim,
            fonte="ANEEL_CACHE",
            consultado_em_utc=str(dados.get("consultado_em_utc", atualizado)),
            registros_consultados=int(dados.get("registros_consultados", 0)),
            azul=dict(dados.get("azul") or {}),
            verde=dict(dados.get("verde") or {}),
            modo_acesso="cache",
            cache_atualizado_em_utc=str(atualizado),
            cache_idade_dias=idade_dias,
            avisos=tuple(avisos),
        )

    def _salvar_cache(self, snapshot: TarifaSnapshot, registros: list[dict[str, Any]]) -> None:
        entradas: list[dict[str, Any]] = []
        if self.cache_path.exists():
            try:
                documento_anterior = json.loads(self.cache_path.read_text(encoding="utf-8"))
                if documento_anterior.get("cache_schema_version") == self.CACHE_SCHEMA_VERSION:
                    entradas = [
                        item
                        for item in documento_anterior.get("entradas", [])
                        if item.get("chave") != self._cache_chave()
                    ]
            except (OSError, json.JSONDecodeError):
                entradas = []

        atualizado = snapshot.consultado_em_utc
        entradas.append({
            "chave": self._cache_chave(),
            "distribuidora": self.distribuidora,
            "grupo": self.grupo,
            "atualizado_em_utc": atualizado,
            "fonte_original": snapshot.fonte,
            "registros": registros,
            "snapshot": snapshot.to_dict(),
        })
        documento = {
            "cache_schema_version": self.CACHE_SCHEMA_VERSION,
            "fonte_url_api": self.API_BASE_URL,
            "fonte_url_csv": self.CSV_URL,
            "atualizado_em_utc": datetime.now(timezone.utc).isoformat(),
            "entradas": entradas,
        }
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporario = self.cache_path.with_suffix(self.cache_path.suffix + ".tmp")
            temporario.write_text(json.dumps(documento, ensure_ascii=False, indent=2), encoding="utf-8")
            temporario.replace(self.cache_path)
        except OSError as exc:
            raise ErroTarifasANEEL(f"Não foi possível gravar o cache tarifário: {self.cache_path}") from exc

    def _buscar_registros(self) -> list[dict[str, Any]]:
        try:
            registros = self._buscar_registros_ckan()
            self._ultima_fonte = "ANEEL_CKAN"
            return registros
        except (requests.RequestException, ErroTarifasANEEL) as erro_ckan:
            try:
                registros = self._buscar_registros_csv()
                self._ultima_fonte = "ANEEL_CSV"
                return registros
            except (requests.RequestException, ErroTarifasANEEL) as erro_csv:
                raise ErroTarifasANEEL(
                    f"Falha na API CKAN ({erro_ckan}); falha no CSV oficial ({erro_csv})"
                ) from erro_csv

    def _buscar_registros_ckan(self) -> list[dict[str, Any]]:
        params = {
            "resource_id": self.RESOURCE_ID,
            "filters": json.dumps({"SigAgente": self.distribuidora, "DscSubGrupo": self.grupo}),
            "limit": 5000,
            "offset": 0,
        }
        resposta = self.session.get(self.API_BASE_URL, params=params, timeout=self.timeout)
        resposta.raise_for_status()
        payload = resposta.json()
        if not payload.get("success"):
            raise ErroTarifasANEEL("Resposta CKAN da ANEEL indicou falha")
        registros = payload.get("result", {}).get("records", [])
        if not registros:
            params.pop("filters")
            params["q"] = self.distribuidora
            resposta = self.session.get(self.API_BASE_URL, params=params, timeout=self.timeout)
            resposta.raise_for_status()
            payload = resposta.json()
            registros = payload.get("result", {}).get("records", [])
        if not registros:
            raise ErroTarifasANEEL(f"Nenhum registro para {self.distribuidora}/{self.grupo}")
        return [dict(registro) for registro in registros]

    def _buscar_registros_csv(self) -> list[dict[str, Any]]:
        resposta = self.session.get(self.CSV_URL, timeout=self.timeout)
        resposta.raise_for_status()
        conteudo = resposta.content
        if isinstance(conteudo, bytes):
            try:
                texto = conteudo.decode("utf-8-sig")
            except UnicodeDecodeError:
                texto = conteudo.decode("latin-1")
        else:
            texto = str(conteudo)
        if not texto.strip():
            raise ErroTarifasANEEL("O CSV oficial da ANEEL veio vazio")

        amostra = texto[:8192]
        try:
            delimitador = csv.Sniffer().sniff(amostra, delimiters=",;|\t").delimiter
        except csv.Error:
            delimitador = ";"

        leitor = csv.DictReader(io.StringIO(texto), delimiter=delimitador)
        registros: list[dict[str, Any]] = []
        distribuidora = _normalizar(self.distribuidora)
        grupo = _normalizar(self.grupo)
        for linha in leitor:
            registro = {
                str(chave).strip().lstrip("\ufeff"): valor
                for chave, valor in linha.items()
                if chave is not None
            }
            agente = _normalizar(registro.get("SigAgente"))
            subgrupo = _normalizar(registro.get("DscSubGrupo"))
            if agente == distribuidora and subgrupo == grupo:
                registros.append(registro)
        if not registros:
            raise ErroTarifasANEEL(f"Nenhum registro CSV para {self.distribuidora}/{self.grupo}")
        return registros

    def _selecionar_vigencia(self, registros: list[dict[str, Any]], referencia: date) -> list[dict[str, Any]]:
        filtrados = [
            registro
            for registro in registros
            if str(registro.get("DscSubGrupo", registro.get("SigSubGrupo", ""))).upper() == self.grupo
        ]
        if not filtrados:
            raise ErroTarifasANEEL(f"Registros sem grupo {self.grupo}")
        aplicacao = [
            registro
            for registro in filtrados
            if "aplica" in _normalizar(registro.get("DscBaseTarifaria"))
        ]
        candidatos = aplicacao or filtrados
        ativos = []
        for registro in candidatos:
            inicio = _data(registro.get("DatInicioVigencia"))
            fim = _data(registro.get("DatFimVigencia"))
            if inicio and inicio <= referencia and (fim is None or referencia <= fim):
                ativos.append(registro)
        if ativos:
            candidatos = ativos
        inicio_max = max((_data(item.get("DatInicioVigencia")) for item in candidatos), default=None)
        if inicio_max is not None:
            candidatos = [item for item in candidatos if _data(item.get("DatInicioVigencia")) == inicio_max]
        return candidatos

    @staticmethod
    def _validar_snapshot(snapshot: TarifaSnapshot) -> None:
        obrigatorios = {
            "azul": ("tusd_ponta_consumo", "tusd_fora_ponta_consumo", "te_ponta", "te_fora_ponta"),
            "verde": ("tusd_demanda", "tusd_ponta_consumo", "tusd_fora_ponta_consumo", "te_ponta", "te_fora_ponta"),
        }
        faltantes = [
            f"{modalidade}.{chave}"
            for modalidade, chaves in obrigatorios.items()
            for chave in chaves
            if snapshot.__getattribute__(modalidade).get(chave, 0.0) <= 0
        ]
        if faltantes:
            raise ErroTarifasANEEL("Tarifa incompleta: " + ", ".join(faltantes))

    def _fallback(self) -> TarifaSnapshot:
        return TarifaSnapshot(
            distribuidora=self.distribuidora,
            grupo=self.grupo,
            vigencia_inicio=None,
            vigencia_fim=None,
            fonte="fallback_local_nao_atualizado",
            consultado_em_utc=datetime.now(timezone.utc).isoformat(),
            registros_consultados=0,
            azul={
                "tusd_ponta_demanda": 46.20,
                "tusd_fora_ponta_demanda": 22.58,
                "tusd_ponta_consumo": 0.89,
                "tusd_fora_ponta_consumo": 0.27,
                "te_ponta": 0.74,
                "te_fora_ponta": 0.58,
            },
            verde={
                "tusd_demanda": 22.58,
                "tusd_ponta_consumo": 0.89,
                "tusd_fora_ponta_consumo": 0.27,
                "te_ponta": 2.61,
                "te_fora_ponta": 0.58,
            },
            modo_acesso="fallback",
            avisos=("Dados locais de fallback; não representam garantia de atualização ANEEL.",),
        )
