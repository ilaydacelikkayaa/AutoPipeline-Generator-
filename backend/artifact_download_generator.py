def generate_artifact_download_step(artifact_name: str) -> dict:
    return {
        "task": "DownloadPipelineArtifact@2",
        "displayName": "Download Build Artifact",
        "inputs": {
            "buildType": "current",
            "artifactName": artifact_name,
            "targetPath": "$(Pipeline.Workspace)/downloaded",
        },
    }
