<html>
<head>
<style>
p{
  width: 50%;
}

a:visited{
  color:blue;
}

a{
text-decoration: none
}

table, th, td {
  border: 1px dotted lightgray;
  border-collapse: collapse;
}
th, td {
  padding: 10px;
}
span.attribution{
  font-style: italic;
  font-size: 13px;
  color: gray;
}

.column {
  float: left;
  width: 50%;
}

.row:after {
  content: "";
  display: table;
  clear: both;
}

span.optional{
  color: gray;
}

a.x{
  opacity: 0.5;
  font-size: 0.8em;
  bottom: 0.3em;
  position: relative;
}

.greendot{
  opacity: 0.5;
  font-size: 0.8em;
}

.alreadyhave{
  text-align: center;
}

</style>
</head>
  <body>
    <h1><span style="color:green">Add New Recipe to Database </span></h1>
    <form action="/add-recipe-to-database" method="POST">
    <label for="recipe"><h2>New Recipe Name</h2></label>
    % if name_taken:
    <input type="text" id="recipe" name="recipe" value="{{recipe}}"><br>
    <span style="color:red">A recipe with that name is already in the database</span>
    % else:
    <input type="text" id="recipe" name="recipe">
    % end
    <br><br><input type="submit" value="Create">
    </form>
  </body>
</html>
