#
# Copyright (c) 2023 Airbyte, Inc., all rights reserved.
#
from __future__ import annotations

import logging
import sys
from typing import Any, Callable, List, Tuple

import asyncclick as click
import dagger
from pipelines import main_logger
from pipelines.airbyte_ci.format.actions import list_files_in_directory
from pipelines.airbyte_ci.format.configuration import Formatter
from pipelines.airbyte_ci.format.consts import DEFAULT_FORMAT_IGNORE_LIST, REPO_MOUNT_PATH, WARM_UP_INCLUSIONS
from pipelines.helpers import sentry_utils
from pipelines.helpers.cli import LogOptions, log_command_results
from pipelines.helpers.utils import sh_dash_c
from pipelines.models.contexts.click_pipeline_context import ClickPipelineContext, pass_pipeline_context
from pipelines.models.steps import CommandResult, StepStatus


class FormatCommand(click.Command):
    """Generic command to run a formatter."""

    def __init__(
        self,
        formatter: Formatter,
        file_filter: List[str],
        get_format_container_fn: Callable,
        format_commands: List[str],
        export_formatted_code: bool,
        *args,
        enable_logging: bool = True,
        exit_on_failure: bool = True,
        **kwargs,
    ) -> None:
        """Initialize a FormatCommand.

        Args:
            formatter (Formatter): The formatter to run
            file_filter (List[str]): The list of files to include in the formatter
            get_format_container_fn (Callable): A function to get the container to run the formatter in
            format_commands (List[str]): The list of commands to run in the container to format the repository
            export_formatted_code (bool): Whether to export the formatted code back to the host
            enable_logging (bool, optional): Make the command log its output. Defaults to True.
            exit_on_failure (bool, optional): Exit the process with status code 1 if the command fails. Defaults to True.
        """
        super().__init__(formatter.value, *args, **kwargs)
        self.formatter = formatter
        self.file_filter = file_filter
        self.get_format_container_fn = get_format_container_fn
        self.format_commands = format_commands
        self.export_formatted_code = export_formatted_code
        self.help = self.get_help_message()
        self.enable_logging = enable_logging
        self.exit_on_failure = exit_on_failure
        self.logger = logging.getLogger(f"Format {self.formatter.value}")

    def get_help_message(self) -> str:
        """Get the help message for the command.

        Returns:
            str: The help message
        """
        message = f"Run {self.formatter.value} formatter"
        if self.export_formatted_code:
            message = f"{message}, will fix any failures."
        else:
            message = f"{message}."
        return message

    def get_dir_to_format(self, dagger_client: dagger.Client) -> dagger.Directory:
        """Get the directory to format according to the file_filter.

        Args:
            dagger_client (dagger.Client): The dagger client to use to get the directory

        Returns:
            dagger.Directory: The directory to format
        """
        return dagger_client.host().directory(".", include=self.file_filter, exclude=DEFAULT_FORMAT_IGNORE_LIST)

    @pass_pipeline_context
    @sentry_utils.with_command_context
    async def invoke(self, ctx: click.Context, click_pipeline_context: ClickPipelineContext) -> Any:
        """Run the command. If exit_on_failure is True, exit the process with status code 1 if the command fails.

        Args:
            ctx (click.Context): The click context
            click_pipeline_context (ClickPipelineContext): The pipeline context

        Returns:
            Any: The result of running the command
        """
        dagger_client = await click_pipeline_context.get_dagger_client(pipeline_name=f"Format {self.formatter.value}")
        dir_to_format = self.get_dir_to_format(dagger_client)
        container = self.get_format_container_fn(dagger_client, dir_to_format)
        command_result = await self.get_format_command_result(dagger_client, container, dir_to_format)
        if (formatted_code_dir := command_result.output_artifact) and self.export_formatted_code:
            await formatted_code_dir.export(".")
        if self.enable_logging:
            log_command_results(ctx, [command_result], main_logger, LogOptions(quiet=ctx.obj["quiet"]))
        if command_result.status is StepStatus.FAILURE and self.exit_on_failure:
            sys.exit(1)
        return command_result

    def disable_logging(self) -> FormatCommand:
        """Disable logging for the command.

        Returns:
            FormatCommand: The command with logging disabled
        """
        self.enable_logging = False
        return self

    def dont_exit_on_failure(self) -> FormatCommand:
        """Don't exit the process with status code 1 if the command fails.

        Returns:
            FormatCommand: The command with exit_on_failure disabled
        """
        self.exit_on_failure = False
        return self

    async def run_format(
        self, dagger_client: dagger.Client, container: dagger.Container, format_commands: List[str], not_formatted_code: dagger.Directory
    ) -> Tuple[dagger.Directory, str, str]:
        """Run the format commands in the container. Return the directory with the modified files, stdout and stderr.

        Args:
            dagger_client (dagger.Client): The dagger client to use
            container (dagger.Container): The container to run the format_commands in
            format_commands (List[str]): The list of commands to run to format the repository
            not_formatted_code (dagger.Directory): The directory with the code to format
        """
        format_container = container.with_exec(sh_dash_c(format_commands), skip_entrypoint=True)
        formatted_directory = format_container.directory(REPO_MOUNT_PATH)
        if warmup_inclusion := WARM_UP_INCLUSIONS.get(self.formatter):
            warmup_dir = dagger_client.host().directory(".", include=warmup_inclusion, exclude=DEFAULT_FORMAT_IGNORE_LIST)
            not_formatted_code = not_formatted_code.with_directory(".", warmup_dir)
        return (
            await not_formatted_code.with_timestamps(0).diff(formatted_directory.with_timestamps(0)),
            await format_container.stdout(),
            await format_container.stderr(),
        )

    async def get_format_command_result(
        self,
        dagger_client: dagger.Client,
        container: dagger.Container,
        not_formatted_code: dagger.Directory,
    ) -> CommandResult:
        """Run a format command and return the CommandResult.
        A command is considered successful if the export operation of run_format is successful and no files were modified.

        Args:
            click_command (click.Command): The click command to run
            container (dagger.Container): The container to run the format_commands in
            not_formatted_code (dagger.Directory): The directory with the code to format
        Returns:
            CommandResult: The result of running the command
        """
        try:
            dir_with_modified_files, stdout, stderr = await self.run_format(
                dagger_client, container, self.format_commands, not_formatted_code
            )
            if await dir_with_modified_files.entries():
                modified_files = await list_files_in_directory(dagger_client, dir_with_modified_files)
                self.logger.debug(f"Modified files: {modified_files}")
                return CommandResult(self, status=StepStatus.FAILURE, stdout=stdout, stderr=stderr, output_artifact=dir_with_modified_files)
            return CommandResult(self, status=StepStatus.SUCCESS, stdout=stdout, stderr=stderr)
        except dagger.ExecError as e:
            return CommandResult(self, status=StepStatus.FAILURE, stderr=e.stderr, stdout=e.stdout, exc_info=e)