"use client";

import { Download, FileText, Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { ContractDetail } from "./types";

const primaryButton = "primary";

export function DocumentTab({
  contract,
  document,
  url,
  isLoading,
  error
}: {
  contract: ContractDetail;
  document: Blob | undefined;
  url: string | null;
  isLoading: boolean;
  error: string | null;
}) {
  if (error) {
    return <section className="panel error">Unable to load this document. {error}</section>;
  }
  if (isLoading || !url || !document) {
    return (
      <section className="document-panel document-panel-loading" aria-label="Loading document" aria-busy="true">
        <Loader2 className="spin" size={24} aria-hidden="true" />
      </section>
    );
  }
  if (contract.mime_type === "application/pdf") {
    return <PdfDocumentView title={contract.title} document={document} />;
  }
  return (
    <section className="panel document-download">
      <FileText size={32} />
      <span>{contract.original_filename || "Original document"}</span>
      <a className={primaryButton} href={url}>
        <Download size={16} /> Download
      </a>
    </section>
  );
}

export function PdfDocumentView({ title, document: pdfBlob }: { title: string; document: Blob }) {
  const pagesRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    let loadingTask: { destroy: () => void | Promise<void> } | null = null;
    let pdfDocument: { destroy: () => void | Promise<void> } | null = null;
    const pages = pagesRef.current;

    const renderDocument = async () => {
      try {
        setError(null);
        setIsLoading(true);
        const pdfjs = await import("pdfjs-dist");
        pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();
        const documentData = new Uint8Array(await pdfBlob.arrayBuffer());
        if (cancelled) return;
        const task = pdfjs.getDocument({ data: documentData });
        loadingTask = task;
        const pdf = await task.promise;
        pdfDocument = pdf;

        for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
          const page = await pdf.getPage(pageNumber);
          const viewport = page.getViewport({ scale: 1.5 });
          const outputScale = Math.min(window.devicePixelRatio || 1, 2);
          const canvas = document.createElement("canvas");
          const context = canvas.getContext("2d");
          if (!context || cancelled) return;

          canvas.width = Math.floor(viewport.width * outputScale);
          canvas.height = Math.floor(viewport.height * outputScale);
          canvas.style.width = `${viewport.width}px`;
          canvas.style.height = `${viewport.height}px`;
          canvas.setAttribute("role", "img");
          canvas.setAttribute("aria-label", `${title}, page ${pageNumber}`);
          await page.render({
            canvasContext: context,
            viewport,
            transform: outputScale === 1 ? undefined : [outputScale, 0, 0, outputScale, 0, 0]
          }).promise;

          if (cancelled) return;
          pages?.append(canvas);
        }
        if (!cancelled) setIsLoading(false);
      } catch (renderError) {
        if (!cancelled) {
          setError(renderError instanceof Error ? renderError.message : "The document could not be displayed.");
          setIsLoading(false);
        }
      }
    };

    void renderDocument();
    return () => {
      cancelled = true;
      pages?.replaceChildren();
      void loadingTask?.destroy();
      void pdfDocument?.destroy();
    };
  }, [title, pdfBlob]);

  return (
    <section className="document-panel document-viewer" aria-label={`${title} document`} aria-busy={isLoading}>
      {error ? <p className="document-render-error">Unable to display this document. {error}</p> : <div className="document-pages" ref={pagesRef} />}
    </section>
  );
}

export function useObjectUrl(blob: Blob | undefined) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!blob) {
      setUrl(null);
      return;
    }
    const nextUrl = URL.createObjectURL(blob);
    setUrl(nextUrl);
    return () => URL.revokeObjectURL(nextUrl);
  }, [blob]);
  return url;
}

