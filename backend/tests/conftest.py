"""Os testes não falam com IA nenhuma.

Sem isto, o degrau local da cascata (`ai.pergunta`) entrava em acção sempre que
os agentes online não respondiam e o Ollama estava a correr no Mac: um único
teste de fumo (`/api/lol/jungle/tips`) passou a demorar 200 segundos à espera do
modelo. Os testes verificam a lógica, não a qualidade das respostas.
"""
import os

os.environ.setdefault("LOCAL_AI", "0")
