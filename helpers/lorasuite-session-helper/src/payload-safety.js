const TOKEN_LIKE_KEYS = [
  "authorization",
  "cookie",
  "cookies",
  "csrf",
  "session",
  "token",
  "x-csrftoken",
];

export function assertNoTokenLikeKeys(value, path = "payload") {
  if (Array.isArray(value)) {
    value.forEach((item, index) => assertNoTokenLikeKeys(item, `${path}[${index}]`));
    return;
  }

  if (!value || typeof value !== "object") {
    return;
  }

  for (const [key, child] of Object.entries(value)) {
    const normalizedKey = key.toLowerCase();
    if (TOKEN_LIKE_KEYS.some((tokenKey) => normalizedKey.includes(tokenKey))) {
      throw new Error(`token-like field is not accepted: ${path}.${key}`);
    }
    assertNoTokenLikeKeys(child, `${path}.${key}`);
  }
}
