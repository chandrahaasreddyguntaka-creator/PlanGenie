/**
 * API functions for authentication with backend database.
 */

const getApiBaseUrl = (): string => {
  return import.meta.env.VITE_API_URL || "/api";
};

export interface User {
  id: number; // int8 from database
  email: string;
  full_name: string;
}

export interface LoginResponse extends User {}

export interface SignupResponse extends User {}

/**
 * Login user.
 */
export async function login(email: string, password: string): Promise<LoginResponse> {
  const apiBaseUrl = getApiBaseUrl();
  
  try {
    const response = await fetch(`${apiBaseUrl}/auth/login`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        email,
        password,
      }),
    });

    if (!response.ok) {
      const error = await response.text();
      throw new Error(error || "Invalid email or password");
    }

    return await response.json();
  } catch (error) {
    console.error("Error during login:", error);
    throw error;
  }
}

/**
 * Sign up new user.
 */
export async function signup(email: string, password: string, fullName: string): Promise<SignupResponse> {
  const apiBaseUrl = getApiBaseUrl();
  
  try {
    const response = await fetch(`${apiBaseUrl}/auth/signup`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        email,
        password,
        full_name: fullName,
      }),
    });

    if (!response.ok) {
      const error = await response.text();
      throw new Error(error || "Failed to create account");
    }

    return await response.json();
  } catch (error) {
    console.error("Error during signup:", error);
    throw error;
  }
}

/**
 * Get current user from localStorage.
 */
export function getCurrentUser(): User | null {
  const USER_KEY = "plangenie_user";
  try {
    const userStr = localStorage.getItem(USER_KEY);
    return userStr ? JSON.parse(userStr) : null;
  } catch {
    return null;
  }
}

/**
 * Set current user in localStorage.
 */
export function setCurrentUser(user: User): void {
  const USER_KEY = "plangenie_user";
  localStorage.setItem(USER_KEY, JSON.stringify(user));
  localStorage.setItem("isAuthenticated", "true");
}

/**
 * Clear current user from localStorage.
 */
export function clearCurrentUser(): void {
  const USER_KEY = "plangenie_user";
  localStorage.removeItem(USER_KEY);
  localStorage.removeItem("isAuthenticated");
  localStorage.removeItem("plangenie_user_id"); // Remove old user_id if exists
}

/**
 * Get current user ID (int8 from database).
 */
export function getCurrentUserId(): number | null {
  const user = getCurrentUser();
  return user ? user.id : null;
}

/**
 * Get user profile information.
 */
export async function getProfile(userId: number): Promise<User> {
  const apiBaseUrl = getApiBaseUrl();
  
  try {
    const response = await fetch(`${apiBaseUrl}/auth/profile?user_id=${userId}`, {
      method: "GET",
      headers: {
        "Content-Type": "application/json",
      },
    });

    if (!response.ok) {
      const error = await response.text();
      throw new Error(error || "Failed to fetch profile");
    }

    return await response.json();
  } catch (error) {
    console.error("Error fetching profile:", error);
    throw error;
  }
}

/**
 * Update user profile information.
 */
export async function updateProfile(userId: number, data: { full_name?: string; email?: string }): Promise<User> {
  const apiBaseUrl = getApiBaseUrl();
  
  try {
    const response = await fetch(`${apiBaseUrl}/auth/profile?user_id=${userId}`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(data),
    });

    if (!response.ok) {
      const error = await response.text();
      throw new Error(error || "Failed to update profile");
    }

    return await response.json();
  } catch (error) {
    console.error("Error updating profile:", error);
    throw error;
  }
}

/**
 * Update user password.
 */
export async function updatePassword(userId: number, currentPassword: string, newPassword: string): Promise<void> {
  const apiBaseUrl = getApiBaseUrl();
  
  try {
    const response = await fetch(`${apiBaseUrl}/auth/password?user_id=${userId}`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
      }),
    });

    if (!response.ok) {
      const error = await response.text();
      throw new Error(error || "Failed to update password");
    }

    return await response.json();
  } catch (error) {
    console.error("Error updating password:", error);
    throw error;
  }
}

