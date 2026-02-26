/**
 * API functions for chat management with backend database.
 */

const getApiBaseUrl = (): string => {
  return import.meta.env.VITE_API_URL || "/api";
};

import { getCurrentUserId } from "./authApi";

// Get current user ID (int8 from database)
const getUserId = (): number => {
  const userId = getCurrentUserId();
  if (!userId) {
    throw new Error("User not logged in. Please log in first.");
  }
  return userId;
};

export interface CreateChatResponse {
  id: string;
  title: string;
}

export interface ChatFromDB {
  id: string; // chat_id from database
  chat_id: string;
  user_id: number; // int8 from database
  title: string;
  created_at: string;
  updated_at?: string;
  chat_memory?: any;
}

/**
 * Create a new chat in the database.
 */
export async function createChat(title?: string): Promise<CreateChatResponse> {
  const apiBaseUrl = getApiBaseUrl();
  const userId = getUserId();
  
  try {
    const response = await fetch(`${apiBaseUrl}/chat/create`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        user_id: userId,
        title: title,
      }),
    });

    if (!response.ok) {
      const error = await response.text();
      throw new Error(`Failed to create chat: ${error}`);
    }

    return await response.json();
  } catch (error) {
    console.error("Error creating chat:", error);
    throw error;
  }
}

/**
 * Delete a chat from the database.
 */
export async function deleteChat(chatId: string): Promise<void> {
  const apiBaseUrl = getApiBaseUrl();
  
  try {
    const response = await fetch(`${apiBaseUrl}/chat/${chatId}`, {
      method: "DELETE",
      headers: {
        "Content-Type": "application/json",
      },
    });

    if (!response.ok) {
      let errorMessage = `Failed to delete chat: ${response.status} ${response.statusText}`;
      try {
        const errorText = await response.text();
        if (errorText) {
          // Try to parse as JSON first
          try {
            const errorJson = JSON.parse(errorText);
            errorMessage = errorJson.detail || errorJson.message || errorText;
          } catch {
            errorMessage = errorText;
          }
        }
      } catch (e) {
        // If we can't read the error text, use the status
      }
      console.error("Delete chat error:", errorMessage);
      throw new Error(errorMessage);
    }
    
    // Response is successful - backend returns {"ok": true}
    // We don't need to parse it, just confirm deletion succeeded
    console.log("Chat deleted successfully");
  } catch (error) {
    console.error("Error deleting chat:", error);
    throw error;
  }
}

/**
 * Get all chats for the current user.
 */
export async function getUserChats(): Promise<ChatFromDB[]> {
  const apiBaseUrl = getApiBaseUrl();
  const userId = getUserId();
  
  try {
    const response = await fetch(`${apiBaseUrl}/chat/user/${userId}`, {
      method: "GET",
    });

    if (!response.ok) {
      const error = await response.text();
      throw new Error(`Failed to fetch chats: ${error}`);
    }

    const data = await response.json();
    return data.chats || [];
  } catch (error) {
    console.error("Error fetching chats:", error);
    throw error;
  }
}

/**
 * Generate a chat title from the user's message.
 */
export async function generateChatTitle(message: string): Promise<string> {
  const apiBaseUrl = getApiBaseUrl();
  
  try {
    const response = await fetch(`${apiBaseUrl}/chat/generate-title`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ message }),
    });

    if (!response.ok) {
      const error = await response.text();
      throw new Error(`Failed to generate title: ${error}`);
    }

    const data = await response.json();
    return data.title || "New Trip Planning";
  } catch (error) {
    console.error("Error generating chat title:", error);
    // Fallback: extract a simple title from the message
    return extractSimpleTitle(message);
  }
}

/**
 * Fallback function to extract a simple title from message.
 */
function extractSimpleTitle(message: string): string {
  // Try to extract destination or key info
  const lowerMessage = message.toLowerCase();
  
  // Look for "from X to Y" pattern
  const fromToMatch = message.match(/from\s+([A-Z]{3}|[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+to\s+([A-Z]{3}|[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)/i);
  if (fromToMatch) {
    return `Trip: ${fromToMatch[1]} → ${fromToMatch[2]}`;
  }
  
  // Look for "to X" pattern
  const toMatch = message.match(/to\s+([A-Z]{3}|[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)/i);
  if (toMatch) {
    return `Trip to ${toMatch[1]}`;
  }
  
  // Look for destination city names (common patterns)
  const cityMatch = message.match(/\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b/);
  if (cityMatch) {
    return `Trip to ${cityMatch[1]}`;
  }
  
  // Default
  return "New Trip Planning";
}

/**
 * Update chat title in the database.
 */
export async function updateChatTitle(chatId: string, title: string): Promise<void> {
  const apiBaseUrl = getApiBaseUrl();
  
  try {
    const response = await fetch(`${apiBaseUrl}/chat/${chatId}/title`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ title }),
    });

    if (!response.ok) {
      const error = await response.text();
      throw new Error(`Failed to update chat title: ${error}`);
    }
  } catch (error) {
    console.error("Error updating chat title:", error);
    throw error;
  }
}

/**
 * Update a chat thread with messages (including content blocks for persistence).
 */
export async function updateChat(chatId: string, messages: any[], title?: string): Promise<void> {
  const apiBaseUrl = getApiBaseUrl();
  
  try {
    const response = await fetch(`${apiBaseUrl}/chat/${chatId}`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ messages, title }),
    });

    if (!response.ok) {
      const error = await response.text();
      throw new Error(`Failed to update chat: ${error}`);
    }
  } catch (error) {
    console.error("Error updating chat:", error);
    throw error;
  }
}

