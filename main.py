from datetime import date
from typing import List
from flask import Flask, abort, render_template, redirect, url_for, flash
from flask_bootstrap import Bootstrap5
from flask_ckeditor import CKEditor
from flask_login import UserMixin, login_user, LoginManager, current_user, logout_user, login_required
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import relationship, DeclarativeBase, Mapped, mapped_column
from sqlalchemy import Integer, String, Text, ForeignKey, event, Boolean
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from forms import CreatePostForm, RegisterForm, LoginForm, CommentForm
from hashlib import md5
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
ckeditor = CKEditor(app)
Bootstrap5(app)

login_manager = LoginManager()
login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# CREATE DATABASE
class Base(DeclarativeBase):
    pass
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(model_class=Base)
db.init_app(app)


# CONFIGURE TABLES
class BlogPost(db.Model):
    __tablename__ = "blog_posts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(250), unique=True, nullable=False)
    subtitle: Mapped[str] = mapped_column(String(250), nullable=False)
    date: Mapped[str] = mapped_column(String(250), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    img_url: Mapped[str] = mapped_column(String(250), nullable=False)
    author_id: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'))
    author: Mapped["User"] = relationship(back_populates="posts")
    comments: Mapped[List['Comment']] = relationship(back_populates='blog')


class User(db.Model, UserMixin):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(250), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(250), unique=True, nullable=False)
    password: Mapped[str] = mapped_column(String(50), nullable=False)
    posts: Mapped[List['BlogPost']] = relationship(back_populates="author")
    comments: Mapped[List['Comment']] = relationship(back_populates='author')
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    @property
    def avatar_url(self):
        cleaned = self.email.strip().lower().encode('utf-8')
        return f'https://www.gravatar.com/avatar/{md5(cleaned).hexdigest()}?s=100&d=identicon'

class Comment(db.Model):
    __tablename__ = "comments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(String, nullable=False)
    author_id: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'))
    author: Mapped['User'] = relationship(back_populates="comments")
    blog_id: Mapped[int] = mapped_column(Integer, ForeignKey('blog_posts.id'))
    blog: Mapped['BlogPost'] = relationship(back_populates="comments")

@event.listens_for(User, 'before_insert')
def set_first_user_as_admin(mapper, connection, target):
    """
    Executes right before a new User row hits the database.
    Checks if this is the first registration record.
    """
    # Use the active connection to count existing users without committing yet
    # We inspect the target's class metadata dynamically
    user_table = target.__table__
    query = db.select(db.func.count()).select_from(user_table)

    # Execute the raw query on the internal connection
    user_count = connection.scalar(query)

    if user_count == 0:
        # If no users exist yet, intercept the model instance and flip the bit
        target.is_admin = True
    else:
        # For user #2 and beyond, ensure it stays False
        target.is_admin = False


with app.app_context():
    db.create_all()

def auth_wrapper(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if current_user.is_authenticated:
            return func(*args, **kwargs)
        else:
            return redirect(url_for('login'))

    return wrapper

def admin_only(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if current_user.id == 1:
            return func(*args, **kwargs)
        else:
            if current_user.is_authenticated:
                return abort(code=403)
            else:
                return abort(code=401)
    return wrapper


@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        email_exists = db.session.execute(db.select(User).where(User.email == form.email.data)).scalar()
        if email_exists:
            flash("Email address already exists", category="error")
            db.session.rollback()
        else:
            hashed_password = generate_password_hash(form.password.data, method='pbkdf2:sha256', salt_length=8)
            new_user = User(name=form.name.data, email=form.email.data, password=hashed_password)
            db.session.add(new_user)
            db.session.commit()
            login_user(new_user)
            flash("Registration successful", category="success")
            return redirect(url_for('get_all_posts'))


    return render_template("register.html", form=form)


@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = db.session.execute(db.Select(User).filter_by(email=form.email.data)).scalar()
        if user is None:
            flash("Invalid email or password", category="error")
        else:
            is_correct = check_password_hash(user.password, form.password.data)
            if is_correct:
                login_user(user)
                return redirect(url_for('get_all_posts'))
            else:
                flash("Invalid email or password", category="error")

    return render_template("login.html", form=form)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route('/')
@auth_wrapper
@login_required
def get_all_posts():
    result = db.session.execute(db.select(BlogPost))
    posts = result.scalars().all()
    return render_template("index.html", all_posts=posts,
                           logged_in=current_user.is_authenticated, is_admin=current_user.is_admin)


@app.route("/post/<int:post_id>", methods=['GET', 'POST'])
@auth_wrapper
@login_required
def show_post(post_id):
    form = CommentForm()
    if form.validate_on_submit():
        new_comment = Comment(
            text=form.comment.data,
            author_id=current_user.id,
            blog_id=post_id,
        )
        db.session.add(new_comment)
        db.session.commit()
        form.comment.data = None
    requested_post = db.get_or_404(BlogPost, post_id)
    comments = db.session.execute(db.select(Comment).filter_by(blog_id=post_id)).scalars().all()
    return render_template("post.html", form=form, comments=comments,
                           post=requested_post, logged_in=current_user.is_authenticated,
                           is_admin=current_user.is_admin)


@app.route("/new-post", methods=["GET", "POST"])
@login_required
@admin_only
def add_new_post():
    form = CreatePostForm()
    if form.validate_on_submit():
        new_post = BlogPost(
            title=form.title.data,
            subtitle=form.subtitle.data,
            body=form.body.data,
            img_url=form.img_url.data,
            author_id=current_user.id,
            date=date.today().strftime("%B %d, %Y")
        )
        db.session.add(new_post)
        db.session.commit()
        return redirect(url_for("get_all_posts"))
    return render_template("make-post.html", form=form,
                           logged_in=current_user.is_authenticated)


@app.route("/edit-post/<int:post_id>", methods=["GET", "POST"])
@login_required
@admin_only
def edit_post(post_id):
    post = db.get_or_404(BlogPost, post_id)
    edit_form = CreatePostForm(
        title=post.title,
        subtitle=post.subtitle,
        img_url=post.img_url,
        author=post.author,
        body=post.body
    )
    if edit_form.validate_on_submit():
        post.title = edit_form.title.data
        post.subtitle = edit_form.subtitle.data
        post.img_url = edit_form.img_url.data
        post.author = current_user
        post.body = edit_form.body.data
        db.session.commit()
        return redirect(url_for("show_post", post_id=post.id))
    return render_template("make-post.html", form=edit_form, is_edit=True,
                           logged_in=current_user.is_authenticated)


@app.route("/delete/<int:post_id>")
@login_required
@admin_only
def delete_post(post_id):
    post_to_delete = db.get_or_404(BlogPost, post_id)
    db.session.delete(post_to_delete)
    db.session.commit()
    return redirect(url_for('get_all_posts'))


@app.route("/about")
def about():
    return render_template("about.html", logged_in=current_user.is_authenticated)


@app.route("/contact")
def contact():
    return render_template("contact.html", logged_in=current_user.is_authenticated)


if __name__ == "__main__":
    app.run(debug=False)
