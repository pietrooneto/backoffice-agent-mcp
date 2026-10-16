"""Interfaccia web minimale dell'agente (Starlette + uvicorn, solo in locale).

La pagina riceve in tempo reale i passi dell'agente (Server-Sent Events) e mostra le richieste
di conferma come schede con i pulsanti Conferma / Rifiuta. Il server ascolta solo su 127.0.0.1.
"""
import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from starlette.routing import Route

from ..agent_loop import Agente
from ..conferma import RichiestaConferma
from ..config import Configurazione
from ..llm import LLMProvider, crea_provider
from ..mcp_client import ClientMcp
from ..registro import Registro

PAGINA = Path(__file__).parent / "static" / "index.html"
HOST_AMMESSI = {"127.0.0.1", "localhost", "[::1]"}
LUNGHEZZA_MASSIMA_RICHIESTA = 2000


class ProtezioneLocale:
    """Middleware ASGI: la pagina e' pensata solo per l'uso locale e per il suo stesso sito.

    Blocca le richieste con Host non locale (DNS rebinding), con Origin di un altro sito (CSRF) e i
    POST che non sono JSON: senza questo, un altro sito aperto nel browser potrebbe "premere"
    Conferma al posto dell'operatore.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            intestazioni = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
            host = intestazioni.get("host", "")
            origine = intestazioni.get("origin")
            rifiuto = None
            if host.rsplit(":", 1)[0] not in HOST_AMMESSI and host not in HOST_AMMESSI:
                rifiuto = PlainTextResponse("Host non ammesso.", status_code=403)
            elif origine and urlparse(origine).netloc != host:
                rifiuto = PlainTextResponse("Origine non ammessa.", status_code=403)
            elif scope["method"] == "POST" and not intestazioni.get("content-type", "").startswith("application/json"):
                rifiuto = PlainTextResponse("Serve application/json.", status_code=415)
            if rifiuto is not None:
                await rifiuto(scope, receive, send)
                return
        await self.app(scope, receive, send)


class Bus:
    """Distribuisce gli eventi a tutte le pagine collegate e li ricorda per chi si collega dopo."""

    def __init__(self) -> None:
        self.storico: list[dict] = []
        self._code: set[asyncio.Queue] = set()

    def pubblica(self, evento: dict) -> None:
        self.storico.append(evento)
        for coda in list(self._code):
            coda.put_nowait(evento)

    def iscrivi(self) -> tuple[asyncio.Queue, list[dict]]:
        coda: asyncio.Queue = asyncio.Queue()
        passato = list(self.storico)  # copiato nello stesso istante dell'iscrizione: niente buchi
        self._code.add(coda)
        return coda, passato

    def disiscrivi(self, coda: asyncio.Queue) -> None:
        self._code.discard(coda)

    def azzera(self) -> None:
        self.storico.clear()
        self.pubblica({"tipo": "nuova_chat"})


class ConfermaWeb:
    """Conferma umana via web: pubblica la richiesta e aspetta che la pagina risponda."""

    def __init__(self, bus: Bus, timeout: float = 600) -> None:
        self.bus = bus
        self.timeout = timeout
        self._in_attesa: dict[str, asyncio.Future] = {}

    async def chiedi(self, richiesta: RichiestaConferma) -> bool:
        id_conferma = uuid.uuid4().hex[:8]
        futuro = asyncio.get_running_loop().create_future()
        self._in_attesa[id_conferma] = futuro
        self.bus.pubblica({
            "tipo": "richiesta_conferma", "id": id_conferma, "tool": richiesta.tool,
            "descrizione": richiesta.descrizione, "argomenti": richiesta.argomenti,
        })
        motivo = None
        try:
            approvata = await asyncio.wait_for(futuro, self.timeout)
        except asyncio.TimeoutError:
            approvata, motivo = False, "scaduta"  # nessuna risposta: per prudenza si considera negata
        finally:
            self._in_attesa.pop(id_conferma, None)
        self.bus.pubblica({"tipo": "conferma_risolta", "id": id_conferma, "approvata": approvata, "motivo": motivo})
        return approvata

    def risolvi(self, id_conferma: str, approva: bool) -> bool:
        futuro = self._in_attesa.get(id_conferma)
        if futuro is None or futuro.done():
            return False
        futuro.set_result(approva)
        return True


class Sessione:
    """Un agente, la sua conversazione e il suo log, condivisi dalle pagine collegate."""

    def __init__(self, config: Configurazione, provider: LLMProvider, mcp: ClientMcp, timeout_conferma: float) -> None:
        self.config, self.provider, self.mcp = config, provider, mcp
        self.bus = Bus()
        self.conferma = ConfermaWeb(self.bus, timeout_conferma)
        self.registro = self._nuovo_registro()
        self.agente = Agente(
            provider, mcp, self.conferma, self.registro,
            max_iterazioni=config.max_iterazioni,
            tentativi_extra_risposta_vuota=config.tentativi_extra_risposta_vuota,
            timeout_tool=config.timeout_tool,
        )
        self.compito: asyncio.Task | None = None

    def _nuovo_registro(self) -> Registro:
        registro = Registro(self.config.log_dir)
        # Alla pagina non servono i messaggi completi inviati al modello: sono solo nel file di log.
        registro.aggiungi_ascoltatore(lambda e: self.bus.pubblica({k: v for k, v in e.items() if k != "nuovi_messaggi"}))
        return registro

    @property
    def occupato(self) -> bool:
        return self.compito is not None and not self.compito.done()

    def nuova_chat(self) -> None:
        self.agente.reset()
        self.registro = self._nuovo_registro()
        self.agente.registro = self.registro
        self.bus.azzera()

    def avvia_richiesta(self, testo: str) -> None:
        self.compito = asyncio.create_task(self._esegui(testo))

    async def _esegui(self, testo: str) -> None:
        try:
            await self.agente.esegui(testo)  # l'evento "arresto" arriva alla pagina dal registro
        except Exception as errore:  # difetto dell'harness: lo si mostra, non si perde in silenzio
            self.registro.scrivi("errore_interno", testo=str(errore))
            self.bus.pubblica({"tipo": "errore", "messaggio": f"Errore interno: {errore}"})


def crea_app(
    config: Configurazione | None = None,
    provider: LLMProvider | None = None,
    env_server: dict[str, str] | None = None,
    timeout_conferma: float = 600,
) -> Starlette:
    config = config or Configurazione.da_ambiente()
    provider = provider or crea_provider(config)

    @asynccontextmanager
    async def ciclo_di_vita(app):
        async with ClientMcp(env_server) as mcp:
            app.state.sessione = Sessione(config, provider, mcp, timeout_conferma)
            yield

    async def pagina(request: Request):
        return FileResponse(PAGINA, media_type="text/html")

    async def stato(request: Request):
        s: Sessione = request.app.state.sessione
        return JSONResponse({
            "provider": s.provider.nome, "modello": s.provider.modello,
            "max_iterazioni": s.config.max_iterazioni, "occupato": s.occupato,
            "sessione_id": s.registro.sessione_id,
            "tool": [{"nome": t.nome, "scrittura": t.scrittura} for t in s.mcp.strumenti],
        })

    async def eventi(request: Request):
        s: Sessione = request.app.state.sessione
        coda, passato = s.bus.iscrivi()

        def formato(evento: dict) -> str:
            return f"data: {json.dumps(evento, ensure_ascii=False)}\n\n"

        async def flusso():
            try:
                for evento in passato:
                    yield formato(evento)
                while True:
                    try:
                        yield formato(await asyncio.wait_for(coda.get(), 15))
                    except asyncio.TimeoutError:
                        if await request.is_disconnected():
                            break
                        yield ": ping\n\n"
            finally:
                s.bus.disiscrivi(coda)

        return StreamingResponse(flusso(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    async def leggi_json(request: Request) -> dict | None:
        try:
            dati = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        return dati if isinstance(dati, dict) else None

    async def messaggio(request: Request):
        s: Sessione = request.app.state.sessione
        dati = await leggi_json(request)
        testo = dati.get("testo") if dati else None
        if not isinstance(testo, str) or not testo.strip():
            return JSONResponse({"errore": "Scrivi una richiesta."}, status_code=400)
        if len(testo) > LUNGHEZZA_MASSIMA_RICHIESTA:
            return JSONResponse({"errore": f"Richiesta troppo lunga (massimo {LUNGHEZZA_MASSIMA_RICHIESTA} caratteri)."}, status_code=400)
        if s.occupato:
            return JSONResponse({"errore": "L'agente sta ancora elaborando la richiesta precedente."}, status_code=409)
        s.avvia_richiesta(testo.strip())
        return JSONResponse({"ok": True}, status_code=202)

    async def conferma(request: Request):
        s: Sessione = request.app.state.sessione
        dati = await leggi_json(request)
        if not dati or not isinstance(dati.get("id"), str) or not isinstance(dati.get("approva"), bool):
            return JSONResponse({"errore": "Richiesta non valida."}, status_code=400)
        if not s.conferma.risolvi(dati["id"], dati["approva"]):
            return JSONResponse({"errore": "Nessuna conferma in attesa con questo id."}, status_code=404)
        return JSONResponse({"ok": True})

    async def nuova(request: Request):
        s: Sessione = request.app.state.sessione
        if s.occupato:
            return JSONResponse({"errore": "Attendi la fine della richiesta in corso."}, status_code=409)
        s.nuova_chat()
        return JSONResponse({"ok": True})

    return Starlette(
        routes=[
            Route("/", pagina),
            Route("/api/stato", stato),
            Route("/api/eventi", eventi),
            Route("/api/messaggio", messaggio, methods=["POST"]),
            Route("/api/conferma", conferma, methods=["POST"]),
            Route("/api/nuova", nuova, methods=["POST"]),
        ],
        middleware=[Middleware(ProtezioneLocale)],
        lifespan=ciclo_di_vita,
    )
