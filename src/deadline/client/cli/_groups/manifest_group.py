# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""
All the `deadline asset` commands:
    * snapshot
    * upload
    * diff
    * download
"""
from __future__ import annotations

import concurrent.futures
import datetime
import glob
import logging
import os
from pathlib import Path
from typing import List

import boto3
import click
from botocore.client import BaseClient

from deadline.client import api
from deadline.job_attachments._aws.aws_clients import (
    get_s3_client,
    get_s3_transfer_manager,
)
from deadline.job_attachments.asset_manifests.base_manifest import (
    BaseAssetManifest,
    BaseManifestPath,
)
from deadline.job_attachments.asset_manifests.decode import decode_manifest
from deadline.job_attachments.caches import HashCache
from deadline.job_attachments.download import download_file_with_s3_key
from deadline.job_attachments.models import (
    S3_MANIFEST_FOLDER_NAME,
    AssetRootManifest,
    JobAttachmentS3Settings,
)
from deadline.job_attachments.upload import FileStatus, S3AssetManager

from ...config import config_file
from ...exceptions import NonValidInputError
from .._common import _apply_cli_options_to_config, _handle_error, _ProgressBarCallbackManager
from .click_logger import ClickLogger


@click.group(name="manifest")
@_handle_error
def cli_manifest():
    """
    Commands to work with AWS Deadline Cloud Job Attachments.
    """


@cli_manifest.command(name="snapshot")
@click.option("--root", required=True, help="The root directory to snapshot. ")
@click.option(
    "--destination",
    default=None,
    help="Destination directory where manifest is created. Defaults to the root directory.",
)
@click.option(
    "--name",
    default=None,
    help="Name of the manifest. A time stamp is added YYYY-MM-DD-HH-MM-SS for versioning.",
)
@click.option(
    "--glob",
    default=None,
    help="Glob include and exclude of directory and file regex to include in the manifest.",
)
@click.option("--diff", default=None, help="Asset Manifest to diff against.")
@click.option("--json", default=None, is_flag=True, help="Output is printed as JSON for scripting")
@_handle_error
def manifest_snapshot(
    root: str, destination: str, name: str, glob: str, diff: str, json: bool, **args
):
    """
    Creates manifest of files specified by root directory.
    """
    logger: ClickLogger = ClickLogger(is_json=json)
    if not os.path.isdir(root):
        raise NonValidInputError(f"Specified root directory {root} does not exist. ")

    if destination and not os.path.isdir(destination):
        raise NonValidInputError(f"Specified destination directory {destination} does not exist. ")
    elif destination is None:
        destination = root
        logger.echo(f"Manifest creation path defaulted to {root} \n")

    inputs = []
    for roots, dirs, files in os.walk(root):
        inputs.extend([str(os.path.join(roots, file)) for file in files])

    # Placeholder Asset Manager
    asset_manager = S3AssetManager(
        farm_id=" ", queue_id=" ", job_attachment_settings=JobAttachmentS3Settings(" ", " ")
    )

    hash_callback_manager: _ProgressBarCallbackManager = None
    if not json:
        hash_callback_manager = _ProgressBarCallbackManager(length=100, label="Hashing Attachments")

    upload_group = asset_manager.prepare_paths_for_upload(
        input_paths=inputs, output_paths=[root], referenced_paths=[]
    )
    assert len(upload_group.asset_groups) == 1

    if upload_group.asset_groups:
        _, manifests = api.hash_attachments(
            asset_manager=asset_manager,
            asset_groups=upload_group.asset_groups,
            total_input_files=upload_group.total_input_files,
            total_input_bytes=upload_group.total_input_bytes,
            print_function_callback=logger.echo,
            hashing_progress_callback=hash_callback_manager.callback if not json else None,
        )
    # This is a hard failure, we are snapshotting 1 directory.
    assert len(manifests) == 1
    output_manifest = manifests[0].asset_manifest

    # If this is a diff manifest, load the supplied manifest file.
    if diff:
        # Parse local manifest
        with open(diff) as source_diff:
            source_manifest_str = source_diff.read()
            source_manifest = decode_manifest(source_manifest_str)

        # Get the differences
        changed_paths: list[str] = []
        differences: list[tuple[FileStatus, BaseManifestPath]] = compare_manifest(
            source_manifest, output_manifest
        )
        for diff_item in differences:
            if diff_item[0] == FileStatus.MODIFIED or diff_item[0] == FileStatus.NEW:
                full_diff_path = f"{full_diff_path}/{diff_item[1].path}"
                changed_paths.append(full_diff_path)
                logger.echo(f"Found difference at: {full_diff_path}, Status: {diff_item[0]}")

        # Since the files are already hashed, we can easily re-use has_attachments to remake a diff manifest.
        diff_group = asset_manager.prepare_paths_for_upload(
            input_paths=changed_paths, output_paths=[root], referenced_paths=[]
        )
        _, diff_manifests = api.hash_attachments(
            asset_manager=asset_manager,
            asset_groups=diff_group.asset_groups,
            total_input_files=diff_group.total_input_files,
            total_input_bytes=diff_group.total_input_bytes,
            print_function_callback=logger.echo,
            hashing_progress_callback=hash_callback_manager.callback if not json else None,
        )
        output_manifest = diff_manifests[0].asset_manifest

    # Write created manifest into local file, at the specified location at destination
    if output_manifest is not None:

        timestamp = datetime.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        manifest_name = name if name else root.replace("/", "_")
        manifest_name = f"{manifest_name}-{timestamp}.manifest"

        local_manifest_file = Path(destination, manifest_name)
        local_manifest_file.parent.mkdir(parents=True, exist_ok=True)
        with open(local_manifest_file, "w") as file:
            file.write(output_manifest.encode())

        # Output results.
        logger.echo(f"Manifest Generated at {destination}{manifest_name}\n")
        json_output: dict = {"manifest": f"{destination}{manifest_name}"}
        logger.json(json_output)
    else:
        # No manifest generated.
        logger.echo("No manifest generated")
        json_output: dict = {}
        logger.json(json_output)


@cli_manifest.command(name="diff")
@click.option("--root", help="The root directory to compare changes to. ")
@click.option(
    "--manifest",
    required=True,
    help="The path to manifest file to diff against.",
)
@click.option(
    "--glob",
    default=None,
    help="Glob include and exclude of directory and file regex to include in the manifest.",
)
@click.option("--json", default=None, is_flag=True, help="Output is printed as JSON for scripting")
@_handle_error
def manifest_diff(root: str, manifest: str, glob: str, json: bool, **args):
    """
    Check file differences between a directory and specified manifest.
    """
    logger: ClickLogger = ClickLogger(is_json=json)
    if not os.path.isfile(manifest):
        raise NonValidInputError(f"Specified manifest file {manifest} does not exist. ")

    if not os.path.isdir(root):
        raise NonValidInputError(f"Specified root directory {root} does not exist. ")

    asset_manager = S3AssetManager(
        farm_id=" ", queue_id=" ", job_attachment_settings=JobAttachmentS3Settings(" ", " ")
    )

    # get inputs of directory
    input_paths = []
    for root_dir, dirs, files in os.walk(root):
        for filename in files:
            file_path = os.path.join(root_dir, filename)
            input_paths.append(Path(file_path))

    # hash and create manifest of local directory
    cache_config = config_file.get_cache_directory()
    with HashCache(cache_config) as hash_cache:
        directory_manifest_object = asset_manager._create_manifest_file(
            input_paths=input_paths, root_path=root, hash_cache=hash_cache
        )

    # parse local manifest
    local_manifest_object: BaseAssetManifest = None
    with open(manifest) as input_file:
        manifest_data_str = input_file.read()
        local_manifest_object = decode_manifest(manifest_data_str)

    # compare manifests
    differences: List[tuple] = compare_manifest(
        reference_manifest=local_manifest_object, compare_manifest=directory_manifest_object
    )

    if json:
        logger.json(f"{differences}")
    else:
        logger.echo(f"\n{root}")
        pretty_print(file_status_list=differences, logger=logger)


@cli_manifest.command(name="download")
@click.argument("download_dir")
@click.option("--profile", help="The AWS profile to use.")
@click.option("--job-id", required=True, help="The AWS Deadline Cloud Job to get. ")
@click.option("--step-id", help="The AWS Deadline Cloud Step to get. ")
@click.option("--farm-id", help="The AWS Deadline Cloud Farm to use. ")
@click.option("--queue-id", help="The AWS Deadline Cloud Queue to use. ")
@click.option("--json", default=None, is_flag=True, help="Output is printed as JSON for scripting")
@_handle_error
def manifest_download(
    download_dir: str,
    profile: str,
    job_id: str,
    step_id: str,
    json: bool,
    **args,
):
    """
    Downloads input manifest of previously submitted job.
    """
    logger: ClickLogger = ClickLogger(is_json=json)
    if not os.path.isdir(download_dir):
        raise NonValidInputError(f"Specified destination directory {download_dir} does not exist. ")

    # setup config
    config = _apply_cli_options_to_config(required_options={"farm_id", "queue_id"}, **args)
    queue_id: str = config_file.get_setting("defaults.queue_id", config=config)
    farm_id: str = config_file.get_setting("defaults.farm_id", config=config)

    deadline: BaseClient = api.get_boto3_client("deadline", config=config)

    queue: dict = deadline.get_queue(
        farmId=farm_id,
        queueId=queue_id,
    )

    # assume queue role - session permissions
    queue_role_session: boto3.Session = api.get_queue_user_boto3_session(
        deadline=deadline,
        config=config,
        farm_id=farm_id,
        queue_id=queue_id,
        queue_display_name=queue["displayName"],
    )

    # get input_manifest_paths from Deadline GetJob API
    job: dict = deadline.get_job(farmId=farm_id, queueId=queue_id, jobId=job_id)
    attachments: dict = job["attachments"]
    input_manifest_paths: list[tuple[str, str]] = [
        (manifest["inputManifestPath"], manifest["rootPath"])
        for manifest in attachments["manifests"]
    ]

    # get s3BucketName from Deadline GetQueue API
    bucket_name: str = queue["jobAttachmentSettings"]["s3BucketName"]

    # get S3 prefix
    s3_prefix: Path = Path(queue["jobAttachmentSettings"]["rootPrefix"], S3_MANIFEST_FOLDER_NAME)

    s3_client: BaseClient = get_s3_client(session=queue_role_session)
    transfer_manager = get_s3_transfer_manager(s3_client=s3_client)

    # download each input_manifest_path
    for input_manifest in input_manifest_paths:
        local_file_name = Path(download_dir, input_manifest[1].replace("/", "-") + ".manifest")

        result = download_file_with_s3_key(
            s3_bucket=bucket_name,
            s3_key=(s3_prefix / input_manifest[0]).as_posix(),
            local_file_name=local_file_name,
            session=queue_role_session,
            transfer_manager=transfer_manager,
        )

        if result is not None:
            # transfer_path = result.meta.call_args.fileobj  # type: ignore[attr-defined]
            # file_size = result.meta.size  # type: ignore[attr-defined]
            logger.echo(f"\nDownloaded manifest file to {local_file_name}.")
        else:
            logger.echo(
                f"\nFailed to download file with S3 key '{input_manifest[0]}' from bucket '{bucket_name}'"
            )


def read_local_manifest(manifest: str) -> BaseAssetManifest:
    """
    Read manifests specified by filepath to manifest folder, returns BaseAssetManifest Object
    """
    input_files = glob.glob(os.path.join(manifest, "*_input"))

    if not input_files:
        raise ValueError(f"No manifest files found in {manifest}")
    elif len(input_files) >= 2:
        raise NonValidInputError(
            f"Multiple input manifest files are not supported, found: {input_files}."
        )

    manifest_file_path = input_files[0]

    with open(manifest_file_path) as input_file:
        manifest_data_str = input_file.read()
        asset_manifest = decode_manifest(manifest_data_str)

        return asset_manifest


def clear_S3_mapping(manifest: str):
    """
    Clears manifest_s3_mapping file contents if it previously exists.
    """
    for filename in os.listdir(manifest):
        if filename.endswith("manifest_s3_mapping"):
            # if S3 mapping already exists, clear contents
            filepath = os.path.join(manifest, filename)
            with open(filepath, "w") as _:
                pass


def diff_manifest(
    asset_manager: S3AssetManager,
    asset_root_manifest: AssetRootManifest,
    manifest: str,
    update: bool,
) -> List[tuple]:
    """
    Gets the file paths in specified manifest if the contents of file have changed since its last snapshot.
    """
    manifest_dir_name = os.path.basename(manifest)
    root_path = asset_root_manifest.root_path
    input_paths: List[Path] = []

    asset_manifest = asset_root_manifest.asset_manifest
    if asset_manifest is None:
        raise NonValidInputError("Manifest object not found, please check input manifest. ")

    for base_manifest_path in asset_manifest.paths:
        if base_manifest_path.path.startswith(manifest_dir_name):
            # skip the manifest folder, or else every upload will need an update after a previous change
            continue
        input_paths.append(Path(root_path, base_manifest_path.path))

    return find_file_with_status(
        asset_manager=asset_manager,
        input_paths=input_paths,
        root_path=root_path,
        update=update,
        statuses=[FileStatus.NEW, FileStatus.MODIFIED],
    )


def find_file_with_status(
    asset_manager: S3AssetManager,
    input_paths: List[Path],
    root_path: str,
    update: bool,
    statuses: List[FileStatus],
) -> List[tuple]:
    """
    Checks a manifest file, compares it to specified root directory or manifest of files with the local hash cache, and finds files that match the specified statuses.
    Returns a list of tuples containing the file information, and its corresponding file status.
    """
    cache_config = config_file.get_cache_directory()

    with HashCache(cache_config) as hash_cache:
        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = {
                executor.submit(
                    asset_manager._process_input_path,
                    path=path,
                    root_path=root_path,
                    hash_cache=hash_cache,
                    update=update,
                ): path
                for path in input_paths
            }
            status_paths: List[tuple] = []
            for future in concurrent.futures.as_completed(futures):
                (file_status, _, manifestPath) = future.result()
                if file_status in statuses:
                    status_paths.append((file_status, manifestPath))

            return status_paths


def update_manifest(manifest: str, new_or_modified_paths: List[tuple]) -> BaseAssetManifest:
    """
    Updates the local manifest file to reflect modified or new files
    """
    input_files = glob.glob(os.path.join(manifest, "*_input"))

    if not input_files:
        raise ValueError(f"No manifest files found in {manifest}")
    elif len(input_files) >= 2:
        raise NonValidInputError(
            f"Multiple input manifest files are not supported, found: {input_files}."
        )

    manifest_file_path = input_files[0]

    with open(manifest_file_path) as manifest_file:
        manifest_data_str = manifest_file.read()
        local_base_asset_manifest = decode_manifest(manifest_data_str)

    # maps paths of local to optimize updating of manifest entries
    manifest_info_dict = {
        base_manifest_path.path: base_manifest_path
        for base_manifest_path in local_base_asset_manifest.paths
    }

    for _, base_asset_manifest in new_or_modified_paths:
        if base_asset_manifest.path in manifest_info_dict:
            # Update the hash_value of the existing object
            manifest_info_dict[base_asset_manifest.path].hash = base_asset_manifest.hash
        else:
            # Add the new object if it doesn't exist
            manifest_info_dict[base_asset_manifest.path] = base_asset_manifest

    # write to local manifest
    updated_path_list = list(manifest_info_dict.values())
    local_base_asset_manifest.paths = updated_path_list
    with open(manifest_file_path, "w") as manifest_file:
        manifest_file.write(local_base_asset_manifest.encode())

    return local_base_asset_manifest


def compare_manifest(
    reference_manifest: BaseAssetManifest, compare_manifest: BaseAssetManifest
) -> List[(tuple)]:
    """
    Compares two manifests, reference_manifest acting as the base, and compare_manifest acting as manifest with changes.
    Returns a list of FileStatus and BaseManifestPath

    """
    reference_dict = {
        manifest_path.path: manifest_path for manifest_path in reference_manifest.paths
    }
    compare_dict = {manifest_path.path: manifest_path for manifest_path in compare_manifest.paths}

    differences = []

    # Find new files
    for file_path, manifest_path in compare_dict.items():
        if file_path not in reference_dict:
            differences.append((FileStatus.NEW, manifest_path))
        elif reference_dict[file_path].hash != manifest_path.hash:
            differences.append((FileStatus.MODIFIED, manifest_path))
        else:
            differences.append((FileStatus.UNCHANGED, manifest_path))

    # Find deleted files
    for file_path, manifest_path in reference_dict.items():
        if file_path not in compare_dict:
            differences.append((FileStatus.DELETED, manifest_path))

    return differences


def pretty_print(file_status_list: List[(tuple)], logger: ClickLogger):
    """
    Prints to command line a formatted file tree structure with corresponding file statuses
    """

    # ASCII characters for the tree structure
    PIPE = "│"
    HORIZONTAL = "──"
    ELBOW = "└"
    TEE = "├"
    SPACE = "    "

    # ANSI escape sequences for colors
    COLORS = {
        "MODIFIED": "\033[93m",  # yellow
        "NEW": "\033[92m",  # green
        "DELETED": "\033[91m",  # red
        "UNCHANGED": "\033[90m",  # grey
        "RESET": "\033[0m",  # base color
        "DIRECTORY": "\033[80m",  # grey
    }

    # Tooltips:
    TOOLTIPS = {
        FileStatus.NEW: " +",  # added files
        FileStatus.DELETED: " -",  # deleted files
        FileStatus.MODIFIED: " M",  # modified files
        FileStatus.UNCHANGED: "",  # unchanged files
    }

    class ColorFormatter(logging.Formatter):
        def format(self, record):
            message = super().format(record)
            return f"{message}"

    # Configure logger
    formatter = ColorFormatter("")
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger = logging.getLogger(__name__)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    def print_tree(directory_tree, prefix=""):
        sorted_entries = sorted(directory_tree.items())

        for i, (entry, subtree) in enumerate(sorted_entries, start=1):
            is_last_entry = i == len(sorted_entries)
            symbol = ELBOW + HORIZONTAL if is_last_entry else TEE + HORIZONTAL
            is_dir = isinstance(subtree, dict)
            color = COLORS["DIRECTORY"] if is_dir else COLORS[subtree.name]
            tooltip = TOOLTIPS[FileStatus.UNCHANGED] if is_dir else TOOLTIPS[subtree]

            message = f"{prefix}{symbol}{color}{entry}{tooltip}{COLORS['RESET']}{os.path.sep if is_dir else ''}"
            logger.info(message)

            if is_dir:
                new_prefix = prefix + (SPACE if is_last_entry else PIPE + SPACE)
                print_tree(subtree, new_prefix)

        if not directory_tree:
            symbol = ELBOW + HORIZONTAL
            message = f"{prefix}{symbol}{COLORS['UNCHANGED']}. {COLORS['RESET']}"
            logger.info(message)

    def build_directory_tree(file_status_list: List[tuple]) -> dict[str, dict]:
        directory_tree: dict = {}

        def add_to_tree(path, status):
            parts = path.split(os.path.sep)
            current_level = directory_tree
            for i, part in enumerate(parts):
                if i == len(parts) - 1:
                    current_level[part] = status
                else:
                    current_level = current_level.setdefault(part, {})

        for status, manifest_path in file_status_list:
            add_to_tree(manifest_path.path, status)
        return directory_tree

    directory_tree = build_directory_tree(file_status_list)
    print_tree(directory_tree)
    logger.info("")
