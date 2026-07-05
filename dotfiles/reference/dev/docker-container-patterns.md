# Docker & Container Patterns

Reference doc for working with Docker, Dockerfiles, and containerized environments.

## Common Pitfalls

### Root permissions
- Container processes running as root can mask permission issues
- `/root` directory has 700 permissions by default — other users can't access it
- When debugging permission errors, check the RUNNING USER first, then the directory permissions
- **Fix symptoms at the cause:** If multiple files in a directory have permission issues, fix the directory permissions, not each file individually

### Dockerfile debugging
- When multiple `RUN` commands fail for the same reason, trace to the common root cause before fixing
- Layer caching means the order of operations matters — put rarely-changing layers first
- `COPY` vs `ADD`: use `COPY` unless you need tar extraction or URL fetching
- Multi-stage builds: don't carry build dependencies into the runtime image

### Environment variables
- `ENV` in Dockerfile sets vars for all subsequent layers AND the running container
- `ARG` is build-time only — not available at runtime
- `.env` files: Docker Compose reads them, but `docker run` needs `--env-file`
- **Subprocess inheritance:** Child processes inherit env vars from the parent process, BUT some orchestrators (systemd, cron, hooks) strip the environment. Never assume an env var exists in a subprocess without verifying.

### Networking
- `localhost` inside a container refers to the container, not the host
- Use `host.docker.internal` (Docker Desktop) or `--network host` to reach the host
- Container-to-container: use Docker networks and service names, not IP addresses

## Checklist Before Writing a Dockerfile

1. What base image? (slim variants preferred)
2. What user will the process run as? (avoid root in production)
3. What ports need exposing?
4. What volumes need mounting?
5. What env vars are required at runtime?
6. Is there a healthcheck?

## Checklist Before Debugging Container Issues

1. What user is the process running as? (`whoami` or check Dockerfile USER)
2. What's the working directory? (`pwd`)
3. Are expected files present? (layer ordering, COPY paths)
4. Are env vars set? (`env | grep KEY`)
5. Can the process reach the network target? (`curl` or `nc`)
