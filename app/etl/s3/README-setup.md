
## How to setup S3



### Step 1 : Create IAM Role for EC2
  
### 🔹 Go to IAM → Roles → Create Role


#### Steps:

1. **Trusted entity** → Select:

   ```
   AWS service → EC2
   ```

2. Attach policy:

   * For now (simple):

     ```
     AmazonS3FullAccess
     ```
   * Later (production): restrict to specific bucket

3. Role name:

   ```
   ec2-s3-access-role
   ```

4. Create role

---

### Step 2: Assign that to EC2

#### 🔹 Go to EC2 → Instances → Select your instance

* Click: **Actions → Security → Modify IAM role**
* Select:

  ```
  ec2-s3-access-role
  ```
* Save

--- 



# ✅ **Step 1: Create S3 Bucket**

### 🔹 Go to AWS Console → S3 → Create Bucket 

### Fill details:

* **Bucket name**: must be globally unique
  Example:

  ```
  audit-system-data-dev
  ```
