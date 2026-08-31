from locust import HttpUser, task, between
import itertools

login_counter = itertools.count(1)
query_counter = itertools.count(1)


class ResearchUser(HttpUser):
    wait_time = between(2, 5)

    def on_start(self):
        user_id = next(login_counter)
        if user_id > 20:
            user_id = ((user_id - 1) % 20) + 1

        email = f"loadtest{user_id}@test.com"
        response = self.client.post("/auth/login", json={
            "email": email,
            "password": "loadtest123"
        })
        self.token = response.json()["access_token"]

    @task
    def run_research(self):
        headers = {"Authorization": f"Bearer {self.token}"}
        query_num = next(query_counter)
        self.client.post("/research", json={
            "query": f"market trends analysis topic number {query_num}"
        }, headers=headers)