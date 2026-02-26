import { useState, useMemo } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Plus, Search, MoreVertical, Archive, Copy, Edit2, Trash2 } from "lucide-react";
import { ChatThread } from "@/types/chat";
import { cn } from "@/lib/utils";
import { format } from "date-fns";

interface ChatSidebarProps {
  threads: ChatThread[];
  activeThreadId?: string;
  onThreadSelect: (id: string) => void;
  onNewThread: () => void;
  onDeleteThread: (id: string) => void;
  onDuplicateThread: (id: string) => void;
  onArchiveThread: (id: string) => void;
  onRenameThread: (id: string, newTitle: string) => void;
  hasEmptyThread: boolean;
}

export function ChatSidebar({
  threads,
  activeThreadId,
  onThreadSelect,
  onNewThread,
  onDeleteThread,
  onDuplicateThread,
  onArchiveThread,
  onRenameThread,
  hasEmptyThread
}: ChatSidebarProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");

  // Memoize filtered threads to prevent recalculation on every render
  const filteredThreads = useMemo(() => {
    if (!searchQuery.trim()) return threads;
    const query = searchQuery.toLowerCase();
    return threads.filter(thread =>
      thread.title.toLowerCase().includes(query)
    );
  }, [threads, searchQuery]);

  const startRename = (thread: ChatThread) => {
    setEditingId(thread.id);
    setEditTitle(thread.title);
  };

  const finishRename = () => {
    if (editingId && editTitle.trim()) {
      onRenameThread(editingId, editTitle.trim());
    }
    setEditingId(null);
  };

  const getPreview = (thread: ChatThread) => {
    const lastMessage = thread.messages[thread.messages.length - 1];
    if (!lastMessage) return "No messages yet";
    const textBlock = lastMessage.content.find(c => c.type === "text");
    if (!textBlock?.text) return "...";
    
    // Handle text that might be an object
    const text = typeof textBlock.text === "string" 
      ? textBlock.text 
      : typeof textBlock.text === "object" 
        ? JSON.stringify(textBlock.text)
        : String(textBlock.text || "");
    
    return text.substring(0, 50) || "...";
  };

  return (
    <div className="flex flex-col h-full bg-sidebar">
      {/* Header */}
      <div className="p-3 border-b border-sidebar-border space-y-3">
        <Button 
          className="w-full bg-primary hover:bg-primary/90 transition-all" 
          onClick={onNewThread}
        >
          <Plus className="h-4 w-4 mr-2" />
          New Chat
        </Button>
        <div className="relative">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search chats..."
            className="pl-9 bg-background border-sidebar-border"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>
      </div>

      {/* Thread List */}
      <ScrollArea className="flex-1">
        {filteredThreads.length === 0 && searchQuery === "" ? (
          <div className="flex flex-col items-center justify-center h-32 text-center p-6">
            <p className="text-sm text-muted-foreground">No trips yet</p>
            <p className="text-xs text-muted-foreground mt-1">Start your first one!</p>
          </div>
        ) : (
          <div className="p-2 space-y-1">
            {filteredThreads.map((thread) => (
              <div
                key={thread.id}
                className={cn(
                  "group relative rounded-lg p-3 pr-10 cursor-pointer hover:bg-sidebar-accent/50 transition-all duration-200",
                  activeThreadId === thread.id && "bg-sidebar-accent border-l-2 border-primary"
                )}
                onClick={(e) => {
                  // Only handle click if not clicking on interactive elements
                  const target = e.target as HTMLElement;
                  if (target.closest('button') || target.closest('input')) {
                    return;
                  }
                  onThreadSelect(thread.id);
                }}
              >
              {/* Three dots menu - positioned in top-right corner */}
              <DropdownMenu>
                <DropdownMenuTrigger asChild onClick={(e) => e.stopPropagation()}>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="absolute top-2 right-2 h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity z-10"
                  >
                    <MoreVertical className="h-4 w-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onClick={(e) => {
                    e.stopPropagation();
                    startRename(thread);
                  }}>
                    <Edit2 className="mr-2 h-4 w-4" />
                    Rename
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={(e) => {
                    e.stopPropagation();
                    onDuplicateThread(thread.id);
                  }}>
                    <Copy className="mr-2 h-4 w-4" />
                    Duplicate
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={(e) => {
                    e.stopPropagation();
                    onArchiveThread(thread.id);
                  }}>
                    <Archive className="mr-2 h-4 w-4" />
                    Archive
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onClick={(e) => {
                      e.stopPropagation();
                      setDeleteId(thread.id);
                    }}
                    className="text-destructive"
                  >
                    <Trash2 className="mr-2 h-4 w-4" />
                    Delete
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>

              {/* Chat content */}
              <div className="thread-item-content">
                {editingId === thread.id ? (
                  <Input
                    value={editTitle}
                    onChange={(e) => setEditTitle(e.target.value)}
                    onBlur={finishRename}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") finishRename();
                      if (e.key === "Escape") setEditingId(null);
                    }}
                    className="h-7 text-sm"
                    autoFocus
                    onClick={(e) => e.stopPropagation()}
                  />
                ) : (
                  <h3 className="font-medium text-sm truncate pr-2">{thread.title}</h3>
                )}
                <p className="text-xs text-muted-foreground truncate mt-1">
                  {getPreview(thread)}
                </p>
                <p className="text-xs text-muted-foreground mt-1">
                  {format(new Date(thread.updatedAt), "MMM d, h:mm a")}
                </p>
              </div>
              </div>
            ))}
          </div>
        )}
      </ScrollArea>

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={!!deleteId} onOpenChange={() => setDeleteId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete chat?</AlertDialogTitle>
            <AlertDialogDescription>
              This action cannot be undone. The chat and all its messages will be permanently deleted.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={async () => {
                if (deleteId) {
                  try {
                    await onDeleteThread(deleteId);
                    setDeleteId(null);
                  } catch (error) {
                    // Error is already handled in the hook with toast
                    // Keep dialog open so user can try again
                    console.error("Failed to delete chat:", error);
                  }
                }
              }}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
