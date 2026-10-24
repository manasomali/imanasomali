from fastapi import FastAPI

# O nginx tira o prefixo /api/ethos antes de repassar a request, então as rotas
# ficam na raiz (/health). O prefixo público é passado ao servidor com
# `uvicorn --root-path /api/ethos`: o parâmetro root_path do FastAPI() está
# obsoleto desde o FastAPI 0.162
app = FastAPI(title="ethos")


@app.get("/health")
def health() -> dict[str, str]:
    # A checagem do banco (SELECT 1, 503 se falhar) entra junto com o db.py
    return {"status": "ok"}
