# MCP Spotify CLI

Agente de línea de comandos (CLI) para controlar Spotify mediante lenguaje natural. Implementa la arquitectura Model Context Protocol (MCP) para separar el servidor de herramientas de Spotify del cliente LLM. Soporta múltiples proveedores de IA (Groq, Gemini, OpenAI).

## Arquitectura

El proyecto consta de dos componentes principales:

* **`mcp_spotify/server.py`**: Servidor MCP que expone la API de Spotify (Spotipy) como tools estandarizadas.
* **`mcp_spotify/agent.py`**: Cliente que interactúa con el usuario, procesa el lenguaje natural mediante adaptadores LLM y ejecuta las tools del servidor con un límite de iteraciones de seguridad para prevenir consumo excesivo de tokens.

## Funcionalidades (Tools)

* `get_current_track`: Obtiene información del track en reproducción.
* `list_devices`: Lista dispositivos activos.
* `search_track` / `search_playlist`: Búsqueda en el catálogo de Spotify.
* `get_my_playlists`: Retorna las playlists guardadas por el usuario autenticado.
* `play`, `pause`, `next_track`, `previous_track`: Control básico de reproducción.
* `set_volume`, `set_shuffle`, `set_repeat`: Control de estado y preferencias.

## Requisitos

* Python 3.12+
* Gestor de paquetes `uv`.
* Cuenta de Spotify Premium (necesaria para los endpoints de control de reproducción).
* App registrada en Spotify Developer Dashboard para obtener Client ID y Client Secret.
* API Keys de los proveedores LLM a utilizar (Groq, Google GenAI, OpenAI).

## Instalación

1. Clonar el repositorio.
2. Instalar dependencias utilizando `uv`:

    ```bash
    uv sync
    ```
    *(Dependencias principales: mcp, spotipy, google-genai, openai, python-dotenv)*.

3. Configurar el archivo `.env` en la raíz del proyecto.

## Configuración (.env)

Crear un archivo `.env` con las siguientes variables:

```env
SPOTIPY_CLIENT_ID="tu_client_id"
SPOTIPY_CLIENT_SECRET="tu_client_secret"
SPOTIPY_REDIRECT_URI="[http://127.0.0.1:8080](http://127.0.0.1:8080)"
GROQ_API_KEY="tu_api_key_de_groq"
GEMINI_API_KEY="tu_api_key_de_google"
OPENAI_API_KEY="tu_api_key_de_openai"
```

## Ejecución
Ejecutar el agente especificando el proveedor y, opcionalmente, el modelo.

**Sintaxis:**

```Bash
uv run mcp-spotify <proveedor> [modelo]
```

## Ejemplo:

Usar Groq (default: llama-3.3-70b-versatile)
```Bash
uv run mcp-spotify groq
```

Usar Gemini (default: models/gemini-2.0-flash)
```Bash
uv run mcp-spotify gemini
```

Usar Gemini con un modelo específico
```Bash
uv run mcp-spotify gemini models/gemini-1.5-flash
```

Modelo de mayor capacidad de razonamiento
```Bash
uv run mcp-spotify gemini models/gemini-2.5-pro
```

Usar un modelo específico de OpenAI
```Bash
uv run mcp-spotify openai gpt-4o
```

## Uso

Una vez iniciado, el prompt permite ingresar comandos en lenguaje natural:

"reproducir mi playlist 'nombre_de_tu_playlist' en modo shuffle"

"baja el volumen al 50% y pasá a la siguiente canción"

"¿qué está sonando?"







---
# Créditos

## 🛠️ Nota de desarrollo y aprendizaje

Este proyecto es una iniciativa de aprendizaje personal con fines educativos. He desarrollado este agente utilizando el **Model Context Protocol (MCP)** y bibliotecas de Python, contando con la asistencia de Inteligencia Artificial para la estructura del código, la resolución de errores y la implementación de buenas prácticas de desarrollo.

Comparto este repositorio con la comunidad como una forma de documentar mi proceso de aprendizaje y con la esperanza de que pueda servir como punto de partida o referencia para alguien que esté explorando la integración de LLMs con APIs externas. 

¡Cualquier feedback, sugerencia de mejora o pull request es más que bienvenido!