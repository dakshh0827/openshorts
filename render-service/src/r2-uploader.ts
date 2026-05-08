import {
  S3Client,
  PutObjectCommand,
  GetObjectCommand,
} from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";
import fs from "node:fs";
import path from "node:path";

/**
 * Get an authenticated Cloudflare R2 client
 */
export function getR2Client(): S3Client {
  const accessKey = process.env.R2_ACCESS_KEY_ID;
  const secretKey = process.env.R2_SECRET_ACCESS_KEY;
  const accountId = process.env.R2_ACCOUNT_ID;

  if (!accessKey || !secretKey || !accountId) {
    throw new Error(
      "Missing R2 credentials: R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ACCOUNT_ID"
    );
  }

  return new S3Client({
    region: "auto",
    endpoint: `https://${accountId}.r2.cloudflarestorage.com`,
    credentials: {
      accessKeyId: accessKey,
      secretAccessKey: secretKey,
    },
  });
}

/**
 * Upload a file to Cloudflare R2
 */
export async function uploadFileToR2(
  filePath: string,
  bucketName: string,
  objectKey: string
): Promise<boolean> {
  try {
    const client = getR2Client();
    const fileContent = fs.readFileSync(filePath);

    const command = new PutObjectCommand({
      Bucket: bucketName,
      Key: objectKey,
      Body: fileContent,
      ContentType: "video/mp4",
    });

    await client.send(command);
    console.log(`[r2] Uploaded ${objectKey} to ${bucketName}`);
    return true;
  } catch (err) {
    console.error(`[r2] Upload failed for ${objectKey}:`, err);
    return false;
  }
}

/**
 * Generate a presigned URL for R2 object access
 */
export async function generatePresignedUrl(
  bucketName: string,
  objectKey: string,
  expirationSeconds: number = 3600
): Promise<string | null> {
  try {
    const client = getR2Client();
    const command = new GetObjectCommand({
      Bucket: bucketName,
      Key: objectKey,
    });

    const url = await getSignedUrl(client, command, {
      expiresIn: expirationSeconds,
    });

    return url;
  } catch (err) {
    console.error(
      `[r2] Failed to generate presigned URL for ${objectKey}:`,
      err
    );
    return null;
  }
}
