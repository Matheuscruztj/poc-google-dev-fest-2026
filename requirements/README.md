# Resoluções de dependências

Os arquivos `py311-*.txt` foram gerados com CPython 3.11.16, pip-tools 7.6.2 e
Linux x86_64. Cada dependência e artefato permitido tem hash SHA-256. Runtime,
desenvolvimento, agente opcional e desenvolvimento com agente têm resoluções
separadas.

Para instalar o ambiente de desenvolvimento:

```bash
python -m pip install --require-hashes -r requirements/py311-dev.txt
python -m pip install --no-deps -e .
```

Para regenerar os locks, use Python 3.11 e compile sem `--upgrade`; isso preserva
as versões existentes e atualiza somente dependências novas ou incompatíveis.
Passe `--upgrade` apenas quando uma atualização deliberada for aprovada.

```bash
python -m pip install pip-tools==7.6.2
pip-compile --generate-hashes -o requirements/py311-runtime.txt pyproject.toml
pip-compile --generate-hashes --extra dev -o requirements/py311-dev.txt pyproject.toml
pip-compile --generate-hashes --extra agent -o requirements/py311-agent.txt pyproject.toml
pip-compile --generate-hashes --extra dev --extra agent -o requirements/py311-dev-agent.txt pyproject.toml
```

Depois da geração, revise e versione os quatro arquivos juntos. A geração deve
rodar em Linux x86_64 com Python 3.11 para manter os marcadores e hashes alinhados
ao CI.
