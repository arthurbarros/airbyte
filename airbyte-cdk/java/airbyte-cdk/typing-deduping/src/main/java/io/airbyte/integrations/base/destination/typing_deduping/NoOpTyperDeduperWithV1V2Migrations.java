/*
 * Copyright (c) 2023 Airbyte, Inc., all rights reserved.
 */

package io.airbyte.integrations.base.destination.typing_deduping;

import static io.airbyte.cdk.integrations.base.IntegrationRunner.TYPE_AND_DEDUPE_THREAD_NAME;
import static io.airbyte.integrations.base.destination.typing_deduping.FutureUtils.getCountOfTypeAndDedupeThreads;
import static java.util.stream.Collectors.toMap;

import io.airbyte.cdk.integrations.destination.StreamSyncSummary;
import io.airbyte.integrations.base.destination.typing_deduping.migrators.Migration;
import io.airbyte.integrations.base.destination.typing_deduping.migrators.MinimumDestinationState;
import io.airbyte.protocol.models.v0.StreamDescriptor;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.locks.Lock;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.lang3.concurrent.BasicThreadFactory;

/**
 * This is a NoOp implementation which skips and Typing and Deduping operations and does not emit
 * the final tables. However, this implementation still performs V1->V2 migrations and V2
 * json->string migrations in the raw tables.
 */
@Slf4j
public class NoOpTyperDeduperWithV1V2Migrations<DestinationState extends MinimumDestinationState> implements TyperDeduper {

  private final List<Migration<DestinationState>> migrations;
  private final ExecutorService executorService;
  private final ParsedCatalog parsedCatalog;
  private final SqlGenerator sqlGenerator;
  private final DestinationHandler<DestinationState> destinationHandler;

  public NoOpTyperDeduperWithV1V2Migrations(final SqlGenerator sqlGenerator,
                                            final DestinationHandler<DestinationState> destinationHandler,
                                            final ParsedCatalog parsedCatalog,
                                            final List<Migration<DestinationState>> migrations) {
    this.sqlGenerator = sqlGenerator;
    this.destinationHandler = destinationHandler;
    this.parsedCatalog = parsedCatalog;
    this.migrations = migrations;
    this.executorService = Executors.newFixedThreadPool(getCountOfTypeAndDedupeThreads(),
        new BasicThreadFactory.Builder().namingPattern(TYPE_AND_DEDUPE_THREAD_NAME).build());
  }

  @Override
  public void prepareSchemasAndRawTables() throws Exception {
    TyperDeduperUtil.prepareSchemas(sqlGenerator, destinationHandler, parsedCatalog);

    List<DestinationInitialState<DestinationState>> destinationInitialStates = TyperDeduperUtil.executeRawTableMigrations(
        executorService,
        destinationHandler,
        migrations,
        destinationHandler.gatherInitialState(parsedCatalog.streams()));

    // Commit the updated destination states.
    // We don't need to trigger any soft resets, because we don't have any final tables.
    destinationHandler.commitDestinationStates(destinationInitialStates.stream().collect(toMap(
        state -> state.streamConfig().id(),
        DestinationInitialState::destinationState)));
  }

  @Override
  public void prepareFinalTables() {
    log.info("Skipping prepareFinalTables");
  }

  @Override
  public void typeAndDedupe(final String originalNamespace, final String originalName, final boolean mustRun) {
    log.info("Skipping TypeAndDedupe");
  }

  @Override
  public Lock getRawTableInsertLock(final String originalNamespace, final String originalName) {
    return new NoOpRawTableTDLock();
  }

  @Override
  public void typeAndDedupe(final Map<StreamDescriptor, StreamSyncSummary> streamSyncSummaries) {
    log.info("Skipping TypeAndDedupe final");
  }

  @Override
  public void commitFinalTables() {
    log.info("Skipping commitFinalTables final");
  }

  @Override
  public void cleanup() {
    log.info("Cleaning Up type-and-dedupe thread pool");
    this.executorService.shutdown();
  }

}
