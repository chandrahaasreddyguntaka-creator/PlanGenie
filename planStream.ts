import { useState, useEffect, useCallback, useMemo } from "react";
import { ChatThread } from "@/types/chat";
import { storage } from "@/lib/storage";
import { createChat, deleteChat, getUserChats, updateChatTitle, updateChat } from "@/lib/chatApi";
import { useToast } from "@/hooks/use-toast";

export function useChatThreads() {
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [loading, setLoading] = useState(true);
  const { toast } = useToast();
  const [deletingIds, setDeletingIds] = useState<Set<string>>(new Set());

  const loadThreads = useCallback(async () => {
    try {
      // Always load from backend first - database is source of truth
      const dbChats = await getUserChats();
      
      // Convert DB format to ChatThread format
      const convertedThreads: ChatThread[] = (dbChats || []).map((dbChat) => {
        // Extract messages from chat_memory
        const chatMemory = dbChat.chat_memory || {};
        const messages = chatMemory.messages || [];
        
        // Convert messages to frontend format
        const frontendMessages = messages.map((msg: any) => {
          // Convert message format from backend to frontend
          const content: any[] = [];
          if (msg.role === "user") {
            // User messages can have content as string or array of content blocks
            if (typeof msg.content === "string") {
              content.push({ type: "text", text: msg.content });
            } else if (Array.isArray(msg.content)) {
              // Content is already in content blocks format - normalize it
              const normalizedBlocks = msg.content.map((block: any) => {
                if (block.type === "text" && block.text !== undefined) {
                  return {
                    ...block,
                    text: typeof block.text === "string" 
                      ? block.text 
                      : typeof block.text === "object" 
                        ? JSON.stringify(block.text)
                        : String(block.text || "")
                  };
                }
                return block;
              });
              content.push(...normalizedBlocks);
            } else {
              // Fallback: try to convert to string
              content.push({ type: "text", text: String(msg.content || "") });
            }
          } else if (msg.role === "assistant") {
            // Assistant messages may have multiple content blocks
            if (typeof msg.content === "string") {
              content.push({ type: "text", text: msg.content });
            } else if (Array.isArray(msg.content)) {
              // Normalize content blocks to ensure text is always a string
              const normalizedBlocks = msg.content.map((block: any) => {
                if (block.type === "text" && block.text !== undefined) {
                  return {
                    ...block,
                    text: typeof block.text === "string" 
                      ? block.text 
                      : typeof block.text === "object" 
                        ? JSON.stringify(block.text)
                        : String(block.text || "")
                  };
                }
                return block;
              });
              content.push(...normalizedBlocks);
            }
          }
          
          return {
            id: msg.id || crypto.randomUUID(),
            role: msg.role,
            createdAt: msg.timestamp || msg.createdAt || new Date().toISOString(),
            content: content.length > 0 ? content : [{ type: "text", text: "" }]
          };
        });
        
        return {
          id: dbChat.id, // This is chat_id from database
          title: dbChat.title,
          createdAt: dbChat.created_at,
          updatedAt: dbChat.updated_at || dbChat.created_at,
          messages: frontendMessages,
          meta: chatMemory.trip_constraints || {},
          archived: false,
          // Store chat_memory for fallback plan extraction
          chat_memory: chatMemory,
        } as ChatThread & { chat_memory?: any };
      });
      
      // Only use database chats - clear localStorage and use DB as source of truth
      setThreads(convertedThreads);
      // Sync to localStorage as backup
      storage.saveThreads(convertedThreads);
    } catch (error) {
      console.error("Failed to load chats from backend:", error);
      
      // Fallback to localStorage if backend fails (for offline/error scenarios)
      const localThreads = storage.getThreads();
      if (localThreads.length > 0) {
        console.warn("Using localStorage as fallback for threads");
        setThreads(localThreads);
        toast({
          title: "Using cached chats",
          description: "Could not load from server. Showing cached chats.",
          variant: "default",
        });
      } else {
        setThreads([]);
        toast({
          title: "Failed to load chats",
          description: "Could not load chats from database. Please refresh the page.",
          variant: "destructive",
        });
      }
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    loadThreads();
  }, [loadThreads]);

  const saveThread = useCallback(async (thread: ChatThread) => {
    // Save to localStorage immediately for fast UI updates
    storage.saveThread(thread);
    
    // Update state only if the thread actually changed (prevent unnecessary re-renders)
    setThreads((prev) => {
      const existingIndex = prev.findIndex(t => t.id === thread.id);
      if (existingIndex >= 0) {
        // Thread exists - only update if it actually changed
        const existing = prev[existingIndex];
        if (existing.updatedAt === thread.updatedAt && 
            existing.messages.length === thread.messages.length &&
            existing.title === thread.title) {
          // No changes detected, return same array reference
          return prev;
        }
        // Thread changed - create new array with updated thread
        const updated = [...prev];
        updated[existingIndex] = thread;
        return updated;
      } else {
        // New thread - add to beginning
        return [thread, ...prev];
      }
    });
    
    // Sync to backend in background (don't await to avoid blocking UI)
    // This ensures messages with content blocks (flights, hotels, itinerary) are persisted
    if (thread.id) {
      try {
        // Update chat with messages (including content blocks) to ensure persistence
        await updateChat(thread.id, thread.messages, thread.title);
        console.log(`✅ Synced thread ${thread.id} to backend with ${thread.messages.length} messages`);
      } catch (error) {
        console.warn("Failed to sync thread to backend:", error);
        // Don't throw - localStorage is still updated, backend sync can retry later
      }
    }
  }, []);

  const createThread = useCallback(async (title?: string): Promise<ChatThread> => {
    try {
      // Create in backend
      const response = await createChat(title);
      
      // Create thread object from response
      const newThread: ChatThread = {
        id: response.id,
        title: response.title,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        messages: [],
        meta: {},
        archived: false,
      };
      
      // Save to localStorage immediately so it's available for navigation
      storage.saveThread(newThread);
      
      // Update local state immediately
      setThreads((prev) => [newThread, ...prev]);
      
      // Refresh threads from database in background to ensure sync
      loadThreads().catch((error) => {
        console.warn("Failed to refresh threads after creation:", error);
      });
      
      return newThread;
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "Unknown error";
      console.error("Failed to create chat in backend:", error);
      
      // Show error toast
      toast({
        title: "Failed to create chat",
        description: errorMessage,
        variant: "destructive",
      });
      
      // Re-throw so caller knows it failed
      throw error;
    }
  }, [loadThreads, toast]);

  const deleteThread = useCallback(async (id: string) => {
    // Mark this thread as being deleted to prevent it from reappearing
    setDeletingIds((prev) => new Set(prev).add(id));
    
    try {
      // Optimistically update UI immediately (remove from state)
      // Use functional update to ensure we have the latest state
      // Create a new array reference to ensure React detects the change
      setThreads((prev) => {
        const filtered = prev.filter((t) => t.id !== id);
        // Also update localStorage immediately
        storage.saveThreads(filtered);
        console.log(`🗑️ Optimistically deleted thread ${id}, remaining threads: ${filtered.length}`);
        return filtered;
      });
      
      // Delete from backend
      await deleteChat(id);
      console.log(`✅ Successfully deleted thread ${id} from backend`);
      
      // Remove from deleting set
      setDeletingIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
      
      // Only refresh threads from database in the background to ensure sync
      // But don't await it - the optimistic update should be enough for immediate UI feedback
      // Refresh after a delay to ensure backend deletion is processed
      // The deleted thread should already be gone from backend, so reload should confirm it
      setTimeout(() => {
        loadThreads().catch((error) => {
          console.warn("Failed to refresh threads after deletion:", error);
          // Don't show error to user - optimistic update already worked
        });
      }, 1000);
      
      toast({
        title: "Chat deleted",
        description: "The chat has been deleted successfully.",
      });
    } catch (error) {
      // Remove from deleting set on error
      setDeletingIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
      
      // If deletion failed, rollback the optimistic update by reloading from backend
      await loadThreads();
      
      const errorMessage = error instanceof Error ? error.message : "Unknown error";
      console.error("Failed to delete chat from backend:", error);
      
      // Show error toast
      toast({
        title: "Failed to delete chat",
        description: errorMessage,
        variant: "destructive",
      });
      
      // Re-throw so caller knows it failed
      throw error;
    }
  }, [loadThreads, toast, deletingIds]);

  const duplicateThread = useCallback((id: string) => {
    const original = threads.find(t => t.id === id);
    if (original) {
      const duplicate: ChatThread = {
        ...original,
        id: crypto.randomUUID(),
        title: `${original.title} (Copy)`,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString()
      };
      saveThread(duplicate);
    }
  }, [threads, saveThread]);

  const archiveThread = useCallback((id: string) => {
    const thread = threads.find(t => t.id === id);
    if (thread) {
      saveThread({ ...thread, archived: true });
    }
  }, [threads, saveThread]);

  const updateThreadTitle = useCallback(async (id: string, title: string) => {
    try {
      // Update in backend first
      await updateChatTitle(id, title);
      
      // Refresh threads from database to ensure sync
      await loadThreads();
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "Unknown error";
      console.error("Failed to update chat title in backend:", error);
      
      // Show error toast
      toast({
        title: "Failed to update chat title",
        description: errorMessage,
        variant: "destructive",
      });
      
      // Don't update UI if backend update failed
      throw error;
    }
  }, [loadThreads, toast]);

  // Memoize filtered arrays to prevent recreating on every render
  // Also filter out threads that are currently being deleted
  const activeThreads = useMemo(() => {
    return threads.filter(t => !t.archived && !deletingIds.has(t.id));
  }, [threads, deletingIds]);
  const archivedThreads = useMemo(() => {
    return threads.filter(t => t.archived && !deletingIds.has(t.id));
  }, [threads, deletingIds]);

  return {
    threads: activeThreads,
    archivedThreads,
    loading,
    saveThread,
    createThread,
    deleteThread,
    duplicateThread,
    archiveThread,
    updateThreadTitle,
    refreshThreads: loadThreads  // Expose refresh function
  };
}
