import openai

# Prompt the user for their OpenAI API key
api_key = input("Enter your OpenAI API key: ").strip()

# Initialize OpenAI client
client = openai.OpenAI(api_key=api_key)

# Define the messages with developer, system, and user roles
messages = [
    {
        "role": "developer",
        "content": "You are a helpful assistant that answers programming questions in the style of somenone from New York City.",
    },
    {
        "role": "system",
        "content": "Ensure responses follow the style and are helpful for programming inquiries.",
    },
    {"role": "user", "content": "Are semicolons optional in JavaScript?"},
]

# Query the model
try:
    response = client.chat.completions.create(model="o4-mini", messages=messages)

    # Print the response
    print("\nResponse from o4-mini:")
    print(response.choices[0].message.content)

except openai.OpenAIError as e:
    print(f"Error: {e}")
