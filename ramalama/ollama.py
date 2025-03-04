import json
import os
import urllib.request
from typing import Optional

from ramalama.common import available, download_file, run_cmd, verify_checksum
from ramalama.model import Model
from ramalama.model_store import SnapshotFile


def fetch_manifest_data(registry_head, model_tag, accept):
    url = f"{registry_head}/manifests/{model_tag}"
    headers = {"Accept": accept}

    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request) as response:
        manifest_data = json.load(response)
    return manifest_data


def pull_config_blob(repos, accept, registry_head, manifest_data, show_progress):
    cfg_hash = manifest_data["config"]["digest"]
    config_blob_path = os.path.join(repos, "blobs", cfg_hash)

    os.makedirs(os.path.dirname(config_blob_path), exist_ok=True)

    url = f"{registry_head}/blobs/{cfg_hash}"
    headers = {"Accept": accept}
    download_file(url, config_blob_path, headers=headers, show_progress=False)


def pull_blob(repos, layer_digest, accept, registry_head, models, model_name, model_tag, model_path, show_progress):
    layer_blob_path = os.path.join(repos, "blobs", layer_digest)
    url = f"{registry_head}/blobs/{layer_digest}"
    headers = {"Accept": accept}
    local_blob = in_existing_cache(model_name, model_tag)
    if local_blob is not None:
        run_cmd(["ln", "-sf", local_blob, layer_blob_path])
    else:
        download_file(url, layer_blob_path, headers=headers, show_progress=show_progress)
        # Verify checksum after downloading the blob
        if not verify_checksum(layer_blob_path):
            print(f"Checksum mismatch for blob {layer_blob_path}, retrying download...")
            os.remove(layer_blob_path)
            download_file(url, layer_blob_path, headers=headers, show_progress=True)
            if not verify_checksum(layer_blob_path):
                raise ValueError(f"Checksum verification failed for blob {layer_blob_path}")

    os.makedirs(models, exist_ok=True)
    relative_target_path = os.path.relpath(layer_blob_path, start=os.path.dirname(model_path))
    run_cmd(["ln", "-sf", relative_target_path, model_path])


def init_pull(repos, accept, registry_head, model_name, model_tag, models, model_path, model, show_progress):
    manifest_data = fetch_manifest_data(registry_head, model_tag, accept)
    pull_config_blob(repos, accept, registry_head, manifest_data, show_progress)
    for layer in manifest_data["layers"]:
        layer_digest = layer["digest"]
        if layer["mediaType"] != "application/vnd.ollama.image.model":
            continue

        pull_blob(repos, layer_digest, accept, registry_head, models, model_name, model_tag, model_path, show_progress)

    return model_path


def in_existing_cache(model_name, model_tag):
    if not available("ollama"):
        return None
    default_ollama_caches = [
        os.path.join(os.environ['HOME'], '.ollama/models'),
        '/usr/share/ollama/.ollama/models',
        'C:\\Users\\%username%\\.ollama\\models',
    ]

    for cache_dir in default_ollama_caches:
        manifest_path = os.path.join(cache_dir, 'manifests', 'registry.ollama.ai', model_name, model_tag)
        if os.access(manifest_path, os.R_OK):
            with open(manifest_path, 'r') as file:
                manifest_data = json.load(file)
                for layer in manifest_data["layers"]:
                    if layer["mediaType"] == "application/vnd.ollama.image.model":
                        layer_digest = layer["digest"]
                        ollama_digest_path = os.path.join(cache_dir, 'blobs', layer_digest)
                        if os.path.exists(str(ollama_digest_path).replace(':', '-')):
                            return str(ollama_digest_path).replace(':', '-')
    return None


class OllamaRepository:

    REGISTRY_URL = "https://registry.ollama.ai/v2/library"
    ACCEPT = "Accept: application/vnd.docker.distribution.manifest.v2+json"

    FILE_NAME_CONFIG = "config.json"
    FILE_NAME_CHAT_TEMPLATE = "chat_template"

    def __init__(self, name):
        self.name = name
        self.registry_head = f"{OllamaRepository.REGISTRY_URL}/{name}"
        self.blob_url = f"{self.registry_head}/blobs"
        self.headers = {"Accept": OllamaRepository.ACCEPT}

    def fetch_manifest(self, tag):
        try:
            return fetch_manifest_data(self.registry_head, tag, OllamaRepository.ACCEPT)
        except urllib.error.HTTPError as e:
            if "Not Found" in e.reason:
                raise KeyError(f"Manifest for {self.name}:{tag} was not found in the Ollama registry")
            raise KeyError(f"failed to fetch manifest: {str(e).strip("'")}")

    def get_file_list(self, tag, cached_files, is_model_in_ollama_cache, manifest=None) -> list[SnapshotFile]:
        if manifest is None:
            manifest = self.fetch_manifest(tag)

        files = []
        if self.name not in cached_files and not is_model_in_ollama_cache:
            model = self.model_file(tag, manifest)
            if model is not None:
                files.append(model)
        if OllamaRepository.FILE_NAME_CONFIG not in cached_files:
            files.append(self.config_file(tag, manifest))
        if OllamaRepository.FILE_NAME_CHAT_TEMPLATE not in cached_files:
            chat_template = self.chat_template_file(tag, manifest)
            if chat_template is not None:
                files.append(chat_template)

        return files

    def get_model_hash(self, manifest) -> str:
        for layer in manifest["layers"]:
            layer_digest = layer["digest"]
            if layer["mediaType"] == "application/vnd.ollama.image.model":
                return layer_digest
        return ""

    def model_file(self, tag, manifest=None) -> Optional[SnapshotFile]:
        if manifest is None:
            manifest = self.fetch_manifest(tag)

        model_digest = self.get_model_hash(manifest)
        if model_digest == "":
            return None

        return SnapshotFile(
            url=f"{self.blob_url}/{model_digest}",
            header=self.headers,
            hash=model_digest,
            name=self.name,
            should_show_progress=True,
            should_verify_checksum=True,
        )

    def config_file(self, tag, manifest=None) -> SnapshotFile:
        if manifest is None:
            manifest = self.fetch_manifest(tag)

        config_hash = manifest["config"]["digest"]

        return SnapshotFile(
            url=f"{self.blob_url}/{config_hash}",
            header=self.headers,
            hash=config_hash,
            name=OllamaRepository.FILE_NAME_CONFIG,
        )

    def get_chat_template_hash(self, manifest) -> str:
        for layer in manifest["layers"]:
            layer_digest = layer["digest"]
            if layer["mediaType"] == "application/vnd.ollama.image.template":
                return layer_digest
        return ""

    def chat_template_file(self, tag, manifest=None) -> Optional[SnapshotFile]:
        if manifest is None:
            manifest = self.fetch_manifest(tag)

        chat_template_digest = self.get_chat_template_hash(manifest)
        if chat_template_digest == "":
            return None

        return SnapshotFile(
            url=f"{self.blob_url}/{chat_template_digest}",
            header=self.headers,
            hash=chat_template_digest,
            name=OllamaRepository.FILE_NAME_CHAT_TEMPLATE,
        )


class Ollama(Model):
    def __init__(self, model):
        super().__init__(model)

        self.type = "Ollama"

    def _local(self, args):
        models = args.store + "/models/ollama"
        if "/" in self.model:
            model_full = self.model
            self._models = os.path.join(models, model_full.rsplit("/", 1)[0])
        else:
            model_full = "library/" + self.model

        if ":" in model_full:
            model_name, model_tag = model_full.split(":", 1)
        else:
            model_name = model_full
            model_tag = "latest"

        model_base = os.path.basename(model_name)
        model_path = os.path.join(models, f"{model_base}:{model_tag}")
        return model_path, models, model_base, model_name, model_tag

    def exists(self, args):
        model_path, _, _, _, _ = self._local(args)
        if not os.path.exists(model_path):
            return None

        return model_path

    def path(self, args):
        model_path, _, _, _, _ = self._local(args)
        if not os.path.exists(model_path):
            raise KeyError(f"{self.model} does not exist")

        return model_path

    def pull(self, args):
        if self.store is not None:
            return self._pull_with_modelstore()

        repos = args.store + "/repos/ollama"
        model_path, models, model_base, model_name, model_tag = self._local(args)
        if os.path.exists(model_path):
            return model_path

        show_progress = not args.quiet
        registry = "https://registry.ollama.ai"
        accept = "Accept: application/vnd.docker.distribution.manifest.v2+json"
        registry_head = f"{registry}/v2/{model_name}"
        try:
            return init_pull(
                repos, accept, registry_head, model_name, model_tag, models, model_path, self.model, show_progress
            )
        except urllib.error.HTTPError as e:
            if "Not Found" in e.reason:
                raise KeyError(f"{self.model} was not found in the Ollama registry")
            raise KeyError(f"failed to pull {registry_head}: " + str(e).strip("'"))

    def model_path(self, args):
        models = args.store + "/models/ollama"
        if "/" in self.model:
            model_full = self.model
            models = os.path.join(models, model_full.rsplit("/", 1)[0])
        else:
            model_full = "library/" + self.model

        if ":" in model_full:
            model_name, model_tag = model_full.split(":", 1)
        else:
            model_name = model_full
            model_tag = "latest"

        model_base = os.path.basename(model_name)
        return os.path.join(models, f"{model_base}:{model_tag}")

    def _pull_with_modelstore(self):
        name, tag, _ = self.extract_model_identifiers()
        hash, cached_files, all = self.store.get_cached_files(tag)
        if all:
            return self.store.get_snapshot_file_path(hash, name)

        ollama_repo = OllamaRepository(self.store.model_name)
        manifest = ollama_repo.fetch_manifest(tag)
        ollama_cache_path = in_existing_cache(self.name, tag)
        is_model_in_ollama_cache = ollama_cache_path is not None
        files: list[SnapshotFile] = ollama_repo.get_file_list(tag, cached_files, is_model_in_ollama_cache)

        model_hash = ollama_repo.get_model_hash(manifest)
        try:
            self.store.new_snapshot(tag, model_hash, files)
        except urllib.error.HTTPError as e:
            if "Not Found" in e.reason:
                raise KeyError(f"{name}:{tag} was not found in the Ollama registry")
            raise KeyError(f"failed to fetch snapshot files: {str(e).strip("'")}")

        # If a model has been downloaded via ollama cli, only create symlink in the snapshots directory
        if is_model_in_ollama_cache:
            snapshot_model_path = self.store.get_snapshot_file_path(model_hash, self.store.model_name)
            os.symlink(ollama_cache_path, snapshot_model_path)

        return self.store.get_snapshot_file_path(model_hash, self.store.model_name)
