import { fileURLToPath } from "node:url";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { selectComposition, renderMedia } from "@remotion/renderer";
import { getBundleLocation } from "./bundle.js";
import { renderJobs } from "./server.js";
import {
  uploadFileToR2,
  generatePresignedUrl,
} from "./r2-uploader.js";

export interface RenderParams {
  renderId: string;
  jobId: string;
  clipIndex: number;
  props: {
    videoUrl: string;
    durationInFrames: number;
    fps: number;
    width: number;
    height: number;
    subtitles: unknown;
    hook: unknown;
    effects: unknown;
  };
}

/**
 * Executes a Remotion render in the background.
 * Updates the in-memory render job map with progress and final status.
 */
export async function executeRender(params: RenderParams): Promise<void> {
  const { renderId, jobId, clipIndex, props } = params;
  const job = renderJobs.get(renderId);

  if (!job) {
    console.error(`[render-worker] Job ${renderId} not found in map`);
    return;
  }

  try {
    job.status = "rendering";
    job.progress = 0;

    console.log(
      `[render-worker] Starting render ${renderId} (job=${jobId}, clip=${clipIndex})`
    );

    const bundleLocation = getBundleLocation();

    // Select the composition with the provided input props
    const composition = await selectComposition({
      serveUrl: bundleLocation,
      id: "ShortVideo",
      inputProps: props,
    });

    // Use system temp directory for temporary file storage
    const tempDir = os.tmpdir();
    const timestamp = Date.now();
    const outputFileName = `remotion_${clipIndex}_${timestamp}.mp4`;
    const tempOutputLocation = path.join(tempDir, outputFileName);

    console.log(
      `[render-worker] Rendering to temp: ${tempOutputLocation}`
    );

    // Render the video to temporary file
    await renderMedia({
      composition,
      serveUrl: bundleLocation,
      codec: "h264",
      crf: 22,
      outputLocation: tempOutputLocation,
      onProgress: ({ progress }) => {
        const percent = Math.round(progress * 100);
        job.progress = percent;

        if (percent % 10 === 0) {
          console.log(`[render-worker] ${renderId} progress: ${percent}%`);
        }
      },
    });

    // Upload rendered file to R2
    const bucketName = process.env.R2_BUCKET || "clips";
    const r2Key = `rendered/${jobId}/${outputFileName}`;

    console.log(`[render-worker] Uploading to R2: s3://${bucketName}/${r2Key}`);

    const uploadSuccess = await uploadFileToR2(
      tempOutputLocation,
      bucketName,
      r2Key
    );

    // Clean up temp file
    if (fs.existsSync(tempOutputLocation)) {
      fs.unlinkSync(tempOutputLocation);
      console.log(`[render-worker] Cleaned up temp file: ${tempOutputLocation}`);
    }

    if (!uploadSuccess) {
      throw new Error(`Failed to upload rendered video to R2`);
    }

    // Generate presigned URL (valid for 24 hours)
    const presignedUrl = await generatePresignedUrl(bucketName, r2Key, 86400);

    if (!presignedUrl) {
      throw new Error(`Failed to generate presigned URL for R2 object`);
    }

    // Success
    job.status = "done";
    job.progress = 100;
    job.outputUrl = presignedUrl;

    console.log(`[render-worker] Render ${renderId} completed`);
    console.log(`[render-worker] Output URL: ${presignedUrl}`);
  } catch (err) {
    job.status = "error";
    job.error = err instanceof Error ? err.message : String(err);

    console.error(`[render-worker] Render ${renderId} failed:`, err);
  }
}
