# Notes on Tech Stack
Dear DAPP2 group members, 

Please read the following notes on the tech stack for this project -- why we use them and how to use them, before making changes/ contributions to this repository.
> Only minimal necessary configurations/ extensions/ dependencies/ frameworks will be used.

## Environment Management
> Why: To avoid "dependency hell" -- code works for one person but crashes for another, or breaks when deployed on the cloud.

### UV: Python Environment
> Why: Never develop on your global/ base environment.
> UV is a package and project manager for Python. UV is significantly faster than Python builtin package and virtual environment modules, pip and venv. 

- [Install UV](https://docs.astral.sh/uv/getting-started/installation/)
- [Quick Tutorial on UV](https://github.com/daveebbelaar/ai-cookbook/tree/main/tools/uv-guide)
- [Official Docs](https://docs.astral.sh/uv/)
- There are 3 main parts in this repo(short for repository or project code base) -- IoT, backend and frontend, each contained within a subfolder with its independent virtual environment (venv). 
  - Please ensure you develop and run your code in the right venv. 
  - All 3 parts/ subfolders are already initiated with ready configuration files. So no need to run ```uv init```.   
- Open one of the subfolders (eg. ```cd iot```) then terminal run ```uv sync``` to create .venv/ with existing depencies.
- Broad Requirements: pyproject.toml
   - ```uv add``` When adding a new dependency/ library, please set a range of versions compatible with the deployment platform eg. AWS or Raspberry Pi.
- Resolved Denpendencies: uv.lock  
  - Should NOT be manually editted as it's auto managed by UV. Human-readable TOML.
- Run code: ```uv run file_name.py```

Note: If you are using VS Code, it may prompt you to choose a Python interpreter. If you are in the project root folder, VS Code may not recognize the subfolder venv. Open subfolders individually or in workspace view then choose the specific venv for this subfolder.

#### Ruff
> Why: Ruff is the fastest Python linter. A linter can find and fix syntax-level bugs, formatting mistakes, and organize imports semi-automatically. It can keep formatting consistent among different developers.

[Official Docs](https://docs.astral.sh/ruff/)

Configurations: ruff.toml
- Install Ruff with UV ```uv tool install ruff```
  - or: VS Code Ruff extension 
- Check errors ```ruff check --diff .``` (`.` to search current folder recursively, or file_name, or path)
- Check and fix err;rs ```ruff check --fix .```  
- Format your code ```ruff format .```

### Docker: OS 
> Why: 

[Official Manual](https://docs.docker.com/manuals/)

