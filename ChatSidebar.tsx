import { ChatThread, UserPreferences } from "@/types/chat";

const THREADS_KEY = "plangenie_threads";
const PREFS_KEY = "plangenie_preferences";

export const storage = {
  getThreads: (): ChatThread[] => {
    try {
      const data = localStorage.getItem(THREADS_KEY);
      return data ? JSON.parse(data) : [];
    } catch {
      return [];
    }
  },

  saveThreads: (threads: ChatThread[]) => {
    localStorage.setItem(THREADS_KEY, JSON.stringify(threads));
  },

  getThread: (id: string): ChatThread | undefined => {
    const threads = storage.getThreads();
    return threads.find(t => t.id === id);
  },

  saveThread: (thread: ChatThread) => {
    const threads = storage.getThreads();
    const index = threads.findIndex(t => t.id === thread.id);
    if (index >= 0) {
      threads[index] = thread;
    } else {
      threads.unshift(thread);
    }
    storage.saveThreads(threads);
  },

  deleteThread: (id: string) => {
    const threads = storage.getThreads().filter(t => t.id !== id);
    storage.saveThreads(threads);
  },

  getPreferences: (): UserPreferences => {
    try {
      const data = localStorage.getItem(PREFS_KEY);
      return data ? JSON.parse(data) : {
        currency: "USD",
        units: "metric",
        theme: "system"
      };
    } catch {
      return {
        currency: "USD",
        units: "metric",
        theme: "system"
      };
    }
  },

  savePreferences: (prefs: UserPreferences) => {
    localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
  }
};
