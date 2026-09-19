/* R2 image uploader — POST /upload stores an image, DELETE /object?key= removes one.
   Both require the X-Upload-Key header; objects live under the dishes/ prefix only. */
const EXT = {
  "image/jpeg": "jpg",
  "image/png": "png",
  "image/webp": "webp",
  "image/gif": "gif",
  "image/avif": "avif",
};

const cors = () => ({
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "POST, DELETE, OPTIONS",
  "access-control-allow-headers": "content-type, x-upload-key",
});

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: cors() });
    }
    const url = new URL(request.url);
    if (
      !env.UPLOAD_KEY ||
      request.headers.get("x-upload-key") !== env.UPLOAD_KEY
    ) {
      return new Response("unauthorized", { status: 401 });
    }

    if (url.pathname === "/upload" && request.method === "POST") {
      const ct = (request.headers.get("content-type") || "")
        .split(";")[0]
        .trim();
      const ext = EXT[ct];
      if (!ext) {
        return Response.json(
          { error: "unsupported content-type: " + ct },
          { status: 415, headers: cors() },
        );
      }
      const key = `dishes/${crypto.randomUUID()}.${ext}`;
      await env.BUCKET.put(key, request.body, {
        httpMetadata: { contentType: ct },
      });
      return Response.json(
        { url: `${env.PUBLIC_URL}/${key}` },
        { headers: cors() },
      );
    }

    if (url.pathname === "/object" && request.method === "DELETE") {
      const key = url.searchParams.get("key") || "";
      if (!key.startsWith("dishes/") || key.includes("..")) {
        return Response.json(
          { error: "invalid key" },
          { status: 400, headers: cors() },
        );
      }
      await env.BUCKET.delete(key);
      return Response.json({ deleted: key }, { headers: cors() });
    }

    return new Response("not found", { status: 404 });
  },
};
