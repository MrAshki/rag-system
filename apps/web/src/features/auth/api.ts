import { apiJson } from "@/lib/api";

export async function requestOtp(phone: string) {
  return apiJson<{ status: string }>("/api/auth/request-otp", {
    method: "POST",
    body: JSON.stringify({ phone }),
  });
}

export async function verifyOtp(phone: string, code: string) {
  return apiJson<{ status: string; is_admin?: boolean }>("/api/auth/verify-otp", {
    method: "POST",
    body: JSON.stringify({ phone, code }),
  });
}

export async function loginWithEmail(email: string, password: string) {
  return apiJson<{ status: string; is_admin?: boolean }>("/api/auth/login-email", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export async function logout() {
  return apiJson<{ status: string }>("/api/auth/logout", {
    method: "POST",
  });
}

export async function sendRegistrationOtp(phone: string) {
  return apiJson<{ status: string }>("/api/auth/register/send-otp", {
    method: "POST",
    body: JSON.stringify({ phone }),
  });
}

export async function verifyRegistrationOtp(phone: string, code: string) {
  return apiJson<{ status: string }>("/api/auth/register/verify-otp", {
    method: "POST",
    body: JSON.stringify({ phone, code }),
  });
}

export async function completeRegistration(payload: {
  phone: string;
  first_name: string;
  last_name: string;
  email: string;
  birth_date: string;
  password: string;
}) {
  return apiJson<{ status: string; is_admin?: boolean }>("/api/auth/register/complete", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
