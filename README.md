## Model Provider

The model provider is selected through the `MODEL_PROVIDER` variable in the `.env` file.

| Value      | Description                                                                          |
| ---------- | ------------------------------------------------------------------------------------ |
| `mock`     | Default. Runs without a database or external keys, and is used for testing and demos. |
| `lmstudio` | A local model running on the user's machine or on the organization's server.          |
| `local`    | A model running inside the organization's server — a future interface.                |

```env
MODEL_PROVIDER=mock
```

**The Mock provider is the default.** It lets you run the project and try out the interfaces without needing any external credentials.

### LM Studio — Local Model

Set `MODEL_PROVIDER=lmstudio` to run a local model through LM Studio. The connection stays inside your machine or the organization's network, and no API key is required.

**Setup:**

1. Install LM Studio and open it.
2. Download the model you want to use.
3. Start the local server.
4. Configure the model settings in the `.env` file.
5. Start the backend and the frontend.
6. Send a message from the interface to confirm the model is working.

Example:

```env
MODEL_PROVIDER=lmstudio
LM_STUDIO_BASE_URL=http://127.0.0.1:1234/v1
LM_STUDIO_MODEL=model-name
LM_STUDIO_TIMEOUT_SECONDS=300
LM_STUDIO_MAX_TOKENS=1500
LM_STUDIO_API_KEY=
```

The local model works with the rest of the system's components, including RAG, sources, conversation history, and per-organization data isolation.

## Running the Project

Requirements:

* Node.js 20 or newer
* Python 3.11 or newer
* Chrome or Edge to try the extension

Running locally does not require setting up any external services.

## Hosting

The system can run on the organization's server or on a local machine, depending on your environment and project requirements.

Never push the `.env` file or any real keys or credentials to the repository. The only file allowed in the repo is `.env.example`, and it must not contain any secret values.
