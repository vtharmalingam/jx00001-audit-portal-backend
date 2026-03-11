
## How to use these models?

```py

# --------------------------------------------
# In Services (Validation before write)
# --------------------------------------------

from models.answer import AnswerModel

data = AnswerModel(**data).dict()
self.s3.write_json(key, data)

# --------------------------------------------
# In Reads
# --------------------------------------------

from models.answer import AnswerModel

data = AnswerModel(**data).dict()
self.s3.write_json(key, data)
```