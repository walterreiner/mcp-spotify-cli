"""
Agente CLI para controlar Spotify via MCP.

Uso:
    uv run mcp-spotify <proveedor> [modelo]

Proveedores disponibles:
    gemini   → usa GEMINI_API_KEY   (default: gemini-2.0-flash)
    groq     → usa GROQ_API_KEY     (default: llama-3.3-70b-versatile)
    openai   → usa OPENAI_API_KEY   (default: gpt-4o-mini)

Ejemplos:
    uv run mcp-spotify gemini
    uv run mcp-spotify gemini gemini-2.0-flash
    uv run mcp-spotify groq llama-3.3-70b-versatile
    uv run mcp-spotify openai gpt-4o-mini
"""

import asyncio
import logging
import json
import os
import sys
from abc import ABC, abstractmethod

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    filename=os.path.join(os.path.dirname(__file__), "agent.log"),
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ── Configuración de proveedores ──────────────────────────────────────────────

PROVIDERS = {
    "gemini": {
        "env_key": "GEMINI_API_KEY",
        "default_model": "gemini-2.0-flash",
    },
    "groq": {
        "env_key": "GROQ_API_KEY",
        "default_model": "llama-3.3-70b-versatile",
    },
    "openai": {
        "env_key": "OPENAI_API_KEY",
        "default_model": "gpt-4o-mini",
    },
}

# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Sos un asistente para controlar Spotify. Reglas estrictas:
1. NUNCA inventes URIs. Siempre buscá primero con search_track o search_playlist.
2. Usá el URI EXACTO que devuelve la búsqueda, sin modificarlo.
3. "NUNCA ejecutes más de una tool en tu respuesta. Si necesitas hacer una búsqueda y luego reproducir, o activar shuffle y luego reproducir, HAZ SOLO LA PRIMERA ACCIÓN y espera el resultado. Está estrictamente prohibido agrupar tool calls.".
4. NUNCA llames get_my_playlists salvo que el usuario diga explícitamente "mis playlists" o "mi playlist".
5. Si el usuario pide información (top 5, recomendaciones, etc.), respondé en texto. No reproduzcas nada.
6. Respondé en español, de forma breve.
7. NUNCA uses nombres de tools que no estén en la lista disponible."""

# ── Adaptadores ───────────────────────────────────────────────────────────────


class LLMAdapter(ABC):
    """Interfaz común para todos los proveedores de LLM."""

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
        self.history = []

    @abstractmethod
    def set_tools(self, mcp_tools) -> None:
        """Recibe las tools del MCP y las convierte al formato del proveedor."""

    @abstractmethod
    async def chat(self, user_input: str) -> tuple[str | None, list[dict]]:
        """
        Manda un mensaje al modelo con el historial actual.
        Devuelve (texto_respuesta, lista_de_tool_calls).
        Si hay tool calls, texto_respuesta puede ser None.
        Cada tool call es: {"name": str, "args": dict, "call_id": str}
        """

    @abstractmethod
    def add_user_message(self, text: str) -> None:
        """Agrega un mensaje del usuario al historial."""

    @abstractmethod
    def add_tool_results(self, results: list[dict]) -> None:
        """
        Agrega los resultados de las tools al historial.
        Cada result es: {"name": str, "call_id": str, "content": str}
        """

    @abstractmethod
    def add_assistant_message(self, text: str) -> None:
        """Agrega la respuesta del asistente al historial."""


class GeminiAdapter(LLMAdapter):
    def __init__(self, api_key: str, model: str):
        super().__init__(api_key, model)
        from google import genai
        from google.genai import types

        self.genai = genai
        self.types = types
        self.client = genai.Client(api_key=api_key)
        self.gemini_tools = []

    def set_tools(self, mcp_tools) -> None:
        self.gemini_tools = [
            self.types.Tool(
                function_declarations=[
                    self.types.FunctionDeclaration(
                        name=t.name,
                        description=t.description,
                        parameters=t.inputSchema,
                    )
                ]
            )
            for t in mcp_tools
        ]

    async def chat(self, user_input: str) -> tuple[str | None, list[dict]]:
        self.add_user_message(user_input)
        response = self.client.models.generate_content(
            model=f"models/{self.model}",
            contents=self.history,
            config=self.types.GenerateContentConfig(
                tools=self.gemini_tools,
                system_instruction=SYSTEM_PROMPT,
            ),
        )
        parts = response.candidates[0].content.parts
        fn_parts = [p for p in parts if hasattr(p, "function_call") and p.function_call]

        if fn_parts:
            self.history.append(
                {
                    "role": "model",
                    "parts": [
                        {
                            "function_call": {
                                "name": p.function_call.name,
                                "args": dict(p.function_call.args),
                            }
                        }
                        for p in fn_parts
                    ],
                }
            )
            tool_calls = [
                {
                    "name": p.function_call.name,
                    "args": dict(p.function_call.args),
                    "call_id": p.function_call.name,
                }
                for p in fn_parts
            ]
            log.debug("Gemini tool_calls: %s", tool_calls)
            return None, tool_calls

        text = " ".join(p.text for p in parts if hasattr(p, "text") and p.text)
        return text, []

    def add_user_message(self, text: str) -> None:
        self.history.append({"role": "user", "parts": [{"text": text}]})

    def add_tool_results(self, results: list[dict]) -> None:
        self.history.append(
            {
                "role": "user",
                "parts": [
                    {
                        "function_response": {
                            "name": r["name"],
                            "response": {"result": r["content"]},
                        }
                    }
                    for r in results
                ],
            }
        )

    def add_assistant_message(self, text: str) -> None:
        self.history.append({"role": "model", "parts": [{"text": text}]})


class OpenAICompatibleAdapter(LLMAdapter):
    """Adaptador para proveedores con API compatible con OpenAI (OpenAI, Groq, etc.)."""

    def __init__(self, api_key: str, model: str, base_url: str):
        super().__init__(api_key, model)
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.openai_tools = []

    def set_tools(self, mcp_tools) -> None:
        self.openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.inputSchema,
                },
            }
            for t in mcp_tools
        ]

    async def chat(self, user_input: str) -> tuple[str | None, list[dict]]:
        self.add_user_message(user_input)
        system = [{"role": "system", "content": SYSTEM_PROMPT}]

        response = self.client.chat.completions.create(
            model=self.model,
            messages=system + self.history,
            tools=self.openai_tools if self.openai_tools else None,
            parallel_tool_calls=False,
        )
        message = response.choices[0].message

        if message.tool_calls:
            self.history.append(message)
            tool_calls = [
                {
                    "name": tc.function.name,
                    "args": __import__("json").loads(tc.function.arguments),
                    "call_id": tc.id,
                }
                for tc in message.tool_calls
            ]
            log.debug("OpenAI-compat tool_calls: %s", tool_calls)
            return None, tool_calls

        text = message.content or ""
        return text, []

    def add_user_message(self, text: str) -> None:
        self.history.append({"role": "user", "content": text})

    def add_tool_results(self, results: list[dict]) -> None:
        for r in results:
            self.history.append(
                {
                    "role": "tool",
                    "tool_call_id": r["call_id"],
                    "content": r["content"],
                }
            )

    def add_assistant_message(self, text: str) -> None:
        self.history.append({"role": "assistant", "content": text})


class GroqAdapter(OpenAICompatibleAdapter):
    def __init__(self, api_key: str, model: str):
        super().__init__(api_key, model, base_url="https://api.groq.com/openai/v1")


class OpenAIAdapter(OpenAICompatibleAdapter):
    def __init__(self, api_key: str, model: str):
        super().__init__(api_key, model, base_url="https://api.openai.com/v1")


# ── Factory ───────────────────────────────────────────────────────────────────


def create_adapter(provider: str, model: str) -> LLMAdapter:
    config = PROVIDERS[provider]
    api_key = os.getenv(config["env_key"])
    if not api_key:
        print(f"❌ Falta la variable de entorno '{config['env_key']}' en el .env")
        sys.exit(1)

    if provider == "gemini":
        return GeminiAdapter(api_key, model)
    elif provider == "groq":
        return GroqAdapter(api_key, model)
    elif provider == "openai":
        return OpenAIAdapter(api_key, model)


# ── Loop agéntico ─────────────────────────────────────────────────────────────

def _calculate_turns(user_input: str) -> int:
    """Calcula el max_turns basado en intents.json"""
    json_path = os.path.join(os.path.dirname(__file__), "intents.json")
    user_text = user_input.lower()

    try:
        with open(json_path, "r", encoding="utf-8") as archivo:
            config = json.load(archivo)
    except FileNotFoundError:
        log.warning("❌ No se encontró intents.json. Usando valor por defecto")
        return 2
    
    for intent in config.get("intents", []):
        if any (keyword in user_text for keyword in intent["keywords"]):
            return intent["max_turns"]
    
    return config.get("default_turns", 2)


async def run_agentic_loop(
    session: ClientSession, adapter: LLMAdapter, user_input: str
) -> str:
    """Loop agéntico con límite dinámico de turnos."""
    
    max_turns = _calculate_turns(user_input)
    log.debug(f'Límite de turnos asignado: {max_turns} para iput: "{user_input}"')
    
    current_input = user_input
    turn = 0

    while turn < max_turns:
        text, tool_calls = await adapter.chat(current_input)

        if not tool_calls:
            adapter.add_assistant_message(text)
            return text

        results = []
        if tool_calls:
            # Tomamos estrictamente la primera herramienta devuelta por el modelo
            tc = tool_calls[0] 
            print(f"  🔧 {tc['name']}({tc['args']})")
            log.debug("Ejecutando tool: %s args=%s", tc["name"], tc["args"])
            try:
                result = await session.call_tool(tc["name"], arguments=tc["args"])
                content = result.content[0].text if result.content else "OK"
            except Exception as e:
                log.error("Error en tool %s: %s", tc["name"], e)
                content = f"Error: {e}"
            print(f"  📦 {content}")
            results.append(
                {"name": tc["name"], "call_id": tc["call_id"], "content": content}
            )

            # Si el modelo intentó mandar más de una herramienta, le avisamos internamente
            if len(tool_calls) > 1:
                log.warning(f"El modelo intentó llamar a {len(tool_calls)} tools. Se ignoraron las adicionales.")
        
        adapter.add_tool_results(results)
        current_input = ""
        turn += 1

    mensaje_corte = "Acción ejecutada. (Bucle detenido por seguridad)."
    adapter.add_assistant_message(mensaje_corte)
    return mensaje_corte


# ── Main ──────────────────────────────────────────────────────────────────────


async def main():
    args = sys.argv[1:]
    if not args or args[0] not in PROVIDERS:
        print(__doc__)
        print(f"Proveedores disponibles: {', '.join(PROVIDERS.keys())}")
        sys.exit(1)

    provider = args[0]
    model = args[1] if len(args) > 1 else PROVIDERS[provider]["default_model"]

    print(f"🤖 Proveedor: {provider} | Modelo: {model}")
    log.info("Iniciando agente. provider=%s model=%s", provider, model)

    adapter = create_adapter(provider, model)

    # Ruta al server dentro de src/
    server_path = os.path.join(os.path.dirname(__file__), "server.py")
    server_params = StdioServerParameters(
        command="python", args=[server_path]
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools_response = await session.list_tools()
            adapter.set_tools(tools_response.tools)

            tool_names = [t.name for t in tools_response.tools]
            print(f"🎵 Tools MCP: {tool_names}")
            print("   Escribí tu petición. ('salir' para terminar)\n")

            while True:
                try:
                    user_input = input("Vos > ").strip()
                except (EOFError, KeyboardInterrupt):
                    print("\nDeteniendo Spotify...")
                    try:
                        await session.call_tool("pause", arguments={})
                    except Exception:
                        pass
                    print("\nChau!")
                    break

                if not user_input:
                    continue
                if user_input.lower() in ("salir", "exit", "quit"):
                    print("Deteniendo Spotify...")
                    try:
                        await session.call_tool("pause", arguments={})
                    except Exception:
                        pass
                    print("Chau!")
                    break

                try:
                    response = await run_agentic_loop(session, adapter, user_input)
                    print(f"\nAgente > {response}\n")
                except Exception as e:
                    log.error("Error en loop principal: %s", e)
                    print(f"\n❌ Error: {e}\n")


def cli():
    asyncio.run(main())


if __name__ == "__main__":
    cli()