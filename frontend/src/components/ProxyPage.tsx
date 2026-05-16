import { useCallback, useState } from "react";
import { useProxies } from "../hooks/useProxies";
import { ProxyList } from "./ProxyList";
import { ProxyForm } from "./ProxyForm";
import { ProxyImportDialog } from "./ProxyImportDialog";
import type { Proxy, ProxyCreateInput, ProxyUpdateInput } from "../lib/proxy";

interface ProxyPageProps {
  currentWorkspaceId: string | null;
}

export function ProxyPage({ currentWorkspaceId }: ProxyPageProps) {
  const {
    proxies,
    loading,
    error,
    create,
    bulkCreate,
    update,
    delete: remove,
    test,
  } = useProxies(currentWorkspaceId);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mode, setMode] = useState<"empty" | "create" | "edit">("empty");
  const [testingId, setTestingId] = useState<string | null>(null);
  const [importOpen, setImportOpen] = useState(false);

  const selected: Proxy | null = proxies.find((p) => p.id === selectedId) ?? null;

  const handleSelect = useCallback((id: string) => {
    setSelectedId(id);
    setMode("edit");
  }, []);

  const handleNew = useCallback(() => {
    setSelectedId(null);
    setMode("create");
  }, []);

  const handleSave = useCallback(
    async (data: ProxyCreateInput | ProxyUpdateInput) => {
      if (mode === "create") {
        const p = await create(data as ProxyCreateInput);
        if (p) {
          setSelectedId(p.id);
          setMode("edit");
        }
      } else if (selectedId) {
        await update(selectedId, data);
      }
    },
    [mode, selectedId, create, update],
  );

  const handleDelete = useCallback(async () => {
    if (!selectedId) return;
    await remove(selectedId);
    setSelectedId(null);
    setMode("empty");
  }, [selectedId, remove]);

  const handleTest = useCallback(
    async (id: string) => {
      setTestingId(id);
      try {
        await test(id);
      } catch (err) {
        const status = (err as { status?: number }).status;
        if (status === 503) {
          alert("Health check is not yet available (httpx missing)");
        }
      } finally {
        setTestingId(null);
      }
    },
    [test],
  );

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-gray-500 text-sm">Loading proxies...</div>
      </div>
    );
  }

  return (
    <div className="h-full flex">
      <div className="w-80 border-r border-border bg-surface-1 flex-shrink-0 overflow-y-auto">
        <ProxyList
          proxies={proxies}
          selectedId={selectedId}
          testingId={testingId}
          onSelect={handleSelect}
          onNew={handleNew}
          onImport={() => setImportOpen(true)}
          onTest={handleTest}
          onDelete={(id) => remove(id)}
        />
        {importOpen && (
          <ProxyImportDialog
            onClose={() => setImportOpen(false)}
            onImport={async (inputs) => {
              const result = await bulkCreate(inputs);
              return result
                ? { created: result.created, failed: result.failed }
                : undefined;
            }}
          />
        )}
      </div>
      <div className="flex-1 overflow-y-auto">
        {error && (
          <div className="px-4 py-2 bg-red-600/15 border-b border-red-600/30 text-red-400 text-sm">
            {error}
          </div>
        )}
        {mode === "empty" && (
          <div className="flex items-center justify-center h-full">
            <p className="text-gray-500 text-sm">Select a proxy or add a new one</p>
          </div>
        )}
        {mode === "create" && (
          <ProxyForm
            proxy={null}
            onSave={handleSave}
            onCancel={() => setMode("empty")}
          />
        )}
        {mode === "edit" && selected && (
          <ProxyForm
            proxy={selected}
            onSave={handleSave}
            onDelete={handleDelete}
            onCancel={() => {
              setSelectedId(null);
              setMode("empty");
            }}
          />
        )}
      </div>
    </div>
  );
}
