import httpx

BASE_URL = "http://localhost:8000"
NUM_USERS = 20

for i in range(1, NUM_USERS + 1):
    email = f"loadtest{i}@test.com"
    password = "loadtest123"

    response = httpx.post(f"{BASE_URL}/auth/register", json={
        "email": email,
        "password": password
    })

    if response.status_code == 201:
        print(f"Created {email}")
    elif response.status_code == 409:
        print(f"{email} already exists, skipping")
    else:
        print(f"Failed to create {email}: {response.text}")