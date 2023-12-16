/*
 * Copyright (c) 2023 Airbyte, Inc., all rights reserved.
 */

package io.airbyte.cdk.integrations.destination.s3;

import com.fasterxml.jackson.databind.JsonNode;
import io.airbyte.cdk.db.AirbyteDestinationConfig;
import javax.annotation.Nonnull;

public class S3DestinationConfigFactory {

  public S3DestinationConfig getS3DestinationConfig(final AirbyteDestinationConfig config, @Nonnull final StorageProvider storageProvider) {
    return S3DestinationConfig.getS3DestinationConfig(config, storageProvider);
  }

}
