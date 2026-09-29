let _token = ''

export function setAuthToken(token: string): void {
  _token = token
}

export function getAuthToken(): string {
  return _token
}
