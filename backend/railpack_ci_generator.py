def generate_railpack_ci_steps(
    build_command: str,
    working_directory: str,
    artifact_name: str,
) -> list:
    ci_steps = [
        {"checkout": "self"},
        {
            "script": ("docker --version\n" "docker buildx version\n" "docker info"),
            "displayName": "Check Docker Environment",
        },
        {
            "script": (
                'mkdir -p "$(Agent.TempDirectory)/railpack-bin"\n'
                "curl -fsSL https://railpack.com/install.sh "
                "-o install-railpack.sh\n"
                "RAILPACK_VERSION=0.43.0 bash install-railpack.sh "
                '--bin-dir "$(Agent.TempDirectory)/railpack-bin"\n'
                'echo "##vso[task.prependpath]$(Agent.TempDirectory)/railpack-bin"\n'
                '"$(Agent.TempDirectory)/railpack-bin/railpack" --version'
            ),
            "displayName": "Install Railpack",
        },
        {
            "script": (
                "docker buildx create "
                "--name autopipeline-builder "
                "--driver docker-container "
                "--use\n"
                "docker buildx inspect autopipeline-builder --bootstrap\n"
                "docker ps --filter name=buildx_buildkit_autopipeline-builder0"
            ),
            "displayName": "Start BuildKit",
        },
        {
            "script": build_command,
            "displayName": "Build with Railpack",
            "workingDirectory": working_directory,
            "env": {
                "BUILDKIT_HOST": "docker-container://buildx_buildkit_autopipeline-builder0"
            },
        },
        *generate_image_artifact_steps(artifact_name),
        {
            "script": "docker buildx rm autopipeline-builder || true",
            "displayName": "Cleanup BuildKit",
            "condition": "always()",
        },
    ]
    return ci_steps


def generate_image_artifact_steps(artifact_name: str) -> list:
    return [
        {
            "script": (
                'mkdir -p "$(Build.ArtifactStagingDirectory)"\n'
                "docker save autopipeline-build:latest "
                '-o "$(Build.ArtifactStagingDirectory)/application.tar"\n'
                'ls -lh "$(Build.ArtifactStagingDirectory)/application.tar"'
            ),
            "displayName": "Export Docker Image",
        },
        {
            "task": "PublishPipelineArtifact@1",
            "displayName": "Publish Pipeline Artifact",
            "inputs": {
                "targetPath": "$(Build.ArtifactStagingDirectory)",
                "artifact": artifact_name,
                "publishLocation": "pipeline",
            },
        },
    ]


def generate_docker_ci_steps(
    working_directory: str,
    artifact_name: str,
    build_platform=None,
) -> list:

    if build_platform not in (None, "linux/amd64", "linux/arm64"):
        raise ValueError(f"Desteklenmeyen platform: {build_platform}")

    steps = [{"checkout": "self"}]

    if build_platform == "linux/arm64":
        steps.append(
            {
                "script": (
                    "docker run --privileged --rm "
                    "tonistiigi/binfmt --install arm64\n"
                    "docker buildx create --use --name autopipeline-builder\n"
                    "docker buildx inspect --bootstrap"
                ),
                "displayName": "Prepare ARM64 Build",
            }
        )

        build_command = (
            "docker buildx build "
            "--platform linux/arm64 "
            "--tag autopipeline-build:latest "
            "--load ."
        )
    else:
        platform_option = f" --platform {build_platform}" if build_platform else ""
        build_command = (
            "docker build --tag autopipeline-build:latest" + platform_option + " ."
        )

    steps.append(
        {
            "script": build_command,
            "displayName": "Build with Dockerfile",
            "workingDirectory": working_directory,
        }
    )

    steps.extend(generate_image_artifact_steps(artifact_name))

    return steps
