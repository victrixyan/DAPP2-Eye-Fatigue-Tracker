# Notes on DevOps & Tech Stack
Dear DAPP2 group members, 

Please read the following notes on the tech stack for this project -- why we use them and how to use them, before making changes/ contributions to this repository.
> Only minimal necessary configurations/ extensions/ dependencies/ frameworks will be used.

# Source control and team collaboration
## Git & GitHub: DevOps
Install and docs: [Git](https://git-scm.com/)

After initiating a project, NEVER directly work on the `main` branch, locally or on Github `origin`. The main branch is for production-ready code. Only merge to main after pull requests on Github. 

- `git clone url`
  - current project repo: https://github.com/victrixyan/DAPP2-Eye-Fatigue-Tracker.git
- `git branch -a` to show all branches
  - `git checkout existing-branch` jump to a branch you want to work on
  - Or `git checkout -b feature/your-feature-name` to start a new branch 
  - Please follow: [branch naming conventions](https://conventional-branch.github.io/)
  - Update to lastest on the branch before new work
  - Common actions: add, commit, push, pull(github to local fetch + merge), rebase, stash ...
- Gihub PR (pull request)
  - ask peers to view your new changes before deciding whether to merge them into the official version `origin/main` branch

Conflicts can happen when two people work on the same file at the same time.
Ideally, everyone work on their own branch to avoid git conflicts.
- .gitignore: git will ignore these files and they will not appear on Gihub.
  - .env contains confidential information e.g. access keys. Therefore .env files will never be pushed to Github or baked into Docker images.

# Environment Management
> Why: To avoid "dependency hell" -- code works for one person but crashes for another, or breaks when deployed on the cloud.

## UV: python environment manager
> Why: UV is a package and project manager for Python.  
UV is significantly faster than Python builtin package manager pip and venv module. (UV and Ruff are written Rust compared to e.g. pip written in Python.) 
UV creates a vitual environment (venv) independent of your global environment with a specified python version and packages needed for a specific project.

[Install UV](https://docs.astral.sh/uv/getting-started/installation/)
| [Tutorial](https://github.com/daveebbelaar/ai-cookbook/tree/main/tools/uv-guide)
| [Official Docs](https://docs.astral.sh/uv/)
- There are 3 main parts in this repo(short for repository or project code base) -- IoT, backend and frontend, each contained within a subfolder with its independent virtual environment. 
  - Please ensure you develop and run your code in the right venv. 
  - All 3 parts/ subfolders are already initiated with ready configuration files. So no need to run ```uv init```.   
- Open one of the subfolders (eg. ```cd iot```) then terminal run ```uv sync``` to create .venv/ with existing depencies.
- Broad Requirements: pyproject.toml
   - ```uv add``` When adding a new dependency/ library, please set a range of versions compatible with the deployment platform eg. AWS or Raspberry Pi.
- Resolved Denpendencies: uv.lock  
  - Should NOT be manually editted as it's auto managed by UV. Human-readable TOML.
- Run code: ```uv run file_name.py```

Note: If you are using VS Code, it may prompt you to choose a Python interpreter. If you are in the project root folder, VS Code may not recognize the subfolder venv. Open subfolders individually or in workspace view then choose the specific venv for this subfolder.

### Ruff: python linter
> Why: Ruff is the fastest Python linter. A linter can find and fix syntax-level bugs, formatting mistakes, and organize imports semi-automatically. It can keep formatting consistent among different developers.

[Official Docs](https://docs.astral.sh/ruff/)

Configurations: ruff.toml
- Install Ruff with UV ```uv tool install ruff```
  - or: VS Code Ruff extension 
- Check errors ```ruff check --diff .``` (`.` to search current folder recursively, or file_name, or path)
- Check and fix err;rs ```ruff check --fix .```  
- Format your code ```ruff format .```

## Docker: cross-platform compatibility
> Why:Docker ensures our software runs smoothly on any machine, regardless of the underlying operating system or hardware. 

Basis: [Containerization](https://www.ibm.com/think/topics/containerization)
| Docker [Official Manual](https://docs.docker.com/manuals/)
| [Install & Tutorial](https://www.docker.com/101-tutorial/)
- A container is a process isolator.
  - Run your software regradless of host OS (iOS, Windows or Linux) or articheture (e.g. ARM64 or x86).
  - venv(managed by UV) is the inner shell and the container(managed by Docker) is the outer shell.
- Containers can be created and deployed with Docker.
- Docker will be used for both backend and frontend. 

- Dockerfile: text-based intructions to build an image `docker build`
  - Dockerfiles are verison control with git & GitHub
  - Docker images are version controlled with [Docker Hub](https://hub.docker.com/)
  - Images are used to create containers
- .dockerignore: ignore these files when building an image
- docker-compse.yml: define all services in one file `docker compose up

# Backend Framework 
## AWS: further data processing and storage 
> Why: AWS has the most mature IoT ecosystem among similar cloud platforms (and this is an IoT-based project). 
### Main Functions
- Ingest data from IoT
  - receive high frequency [MQTT](https://mqtt.org/) ([IoT Core](https://aws.amazon.com/iot-core/) as broker) messages/ data points from Pi
- Realtime feature extraction from metrics ([Lambda](https://aws.amazon.com/lambda/))
  - use a sliding window to calculate e.g. blinking rate, fixation time, pupil size over a set time window
  - store in database ([Timestream](https://aws.amazon.com/timestream/) for time-series data)
- Fatigue prediction
#### A potential way to achieve personalized dynamic eye fatigue detection:
- Calibration: use the first e.g. 5min in a session to set a data baseline
    - start calibration when not feeling eye fatigue
- Calculate statistical derivatives from features e.g. z-score(anomaly) and CUSUM(trend) of blinking rates
- Unsupervised Learning with isolated forest
  - feed in both raw and statistical features 
  - return a 'fatigue score' from 0-100
- A potential problem of this method: the distribution becomes skewed overtime leading to concept shift. Therefore, the model won't improve in performance with more data.
There may need to be a maximum session duration to cap the distribution shift in all parameters/ features.

## FastAPI: 
> Why: It is the fastest Python framework for handling concurrent connections (essential for real-time monitoring) and automatically generates interactive documentation for APIs. 
- The frontend only interact directly with the backend. IoT/Pi only talks directly to the backend. Any interaction between IoT and frontend will be mediated though backend APIs.
- Bidirectional control: sends commands to IoT
- WebSockets: maintains a live connection with the frontend


# Frontend Framework
Not deciced yet.
- Potential Python-based Frameworks: Streamlit, /Reflex, Dash ...
##
### A few basic functions:
- Simple registeration/ login portal
  - get user identifers for the database to organize data by user_id
- Start/ end session button
  - messages backend which then messages IoT
- Realtime user interface
  - request data from backend constantly
  - user feed back and visuals